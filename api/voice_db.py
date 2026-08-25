"""음성 상담 흐름(POST /api/sessions ...)이 쓰는 DB 접근 계층.

job.db는 SQLAlchemy가 만든 스키마(sessions / session_answers / session_recommendations)를
쓰고 있고, conversation_schema.sql은 적용되어 있지 않다. 여기서는 그 실제 스키마를 그대로
쓰고, 음성 답변 저장에 필요한 만큼만 컬럼/테이블을 덧붙인다(ensure_voice_schema).

외부 계약의 questionKey(C~G)는 프론트의 고정 5문항이고, 기존 questions 테이블의
step(B/D/E/F)과는 질문 내용이 다르다. 그래서 step을 재사용하지 않고 voice_questions
매핑 테이블을 따로 두어 "계약상 questionKey <-> 내부 질문/태그 분류"를 연결한다.
"""

import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from db import JOBS_SQL, get_db

# 세션 수명 정책 (프론트 v4 계약의 idleTimeoutSeconds / maxTtlSeconds와 동일한 값)
IDLE_TIMEOUT_SECONDS = 120
MAX_TTL_SECONDS = 1200

# 프론트 고정 5문항. (questionKey, 태그 분류, 성격, 순서, 질문 문구)
#   positive  : 추천 점수를 올리는 신호 (해본 일 / 하고 싶은 일 / 자신 있는 일)
#   difficult : 해당 조건이 걸린 직업을 제외하는 신호 (하기 어려운 일)
#   cert      : 자격증 보유 여부. 없다고 하면 자격증이 필요한 직업을 빼준다.
VOICE_QUESTIONS = [
    ("C", "HARD", "difficult", 1, "하기 어려운 일이 있으신가요?"),
    ("D", "EXP", "positive", 2, "예전에 어떤 일을 해보셨나요?"),
    ("E", "EXP", "positive", 3, "앞으로 어떤 일을 하고 싶으신가요?"),
    ("F", "CAN", "positive", 4, "어떤 일에 자신이 있으신가요?"),
    ("G", "CERT", "cert", 5, "가지고 계신 자격증이 있으신가요?"),
]
QUESTION_KEYS = [key for key, _, _, _, _ in VOICE_QUESTIONS]

# 추천을 만들려면 최소한 이 답변들이 있어야 한다.
# C(하기 어려운 일)와 G(자격증)는 걸러내는 조건이라 없어도 추천을 만들 수 있다.
REQUIRED_QUESTION_KEYS = ["D", "E", "F"]

# G(자격증) 답변을 담기 위해 tags에 추가하는 분류.
CERT_TAGS = [
    ("CERT_있음", "자격증이 있어요", "자격증·면허를 보유하고 있다고 답한 경우"),
    ("CERT_없음", "자격증이 없어요", "자격증이 없거나 모르겠다고 답한 경우"),
]


# --- 시간 유틸 -------------------------------------------------------------
# sqlite에는 기존 행과 같은 형식("YYYY-MM-DD HH:MM:SS")으로 UTC를 저장하고,
# API 응답에서는 ISO 8601 + Z로 바꿔 내보낸다.

_SQL_FMT = "%Y-%m-%d %H:%M:%S"


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def to_sql(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime(_SQL_FMT)


def from_sql(value: str) -> datetime:
    """DB에 들어있는 datetime 문자열을 UTC aware datetime으로 되돌린다."""
    text = str(value).strip().replace("T", " ").rstrip("Z")
    return datetime.strptime(text[:19], _SQL_FMT).replace(tzinfo=timezone.utc)


def to_iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# --- 스키마 보정 -----------------------------------------------------------

_VOICE_ANSWERS_DDL = """
CREATE TABLE IF NOT EXISTS session_voice_answers (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id    VARCHAR(36) NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    question_key  VARCHAR(2)  NOT NULL,
    stt_text      TEXT        NOT NULL,
    keywords      TEXT        NOT NULL DEFAULT '[]',
    confidence    REAL,
    audio_format  VARCHAR(20),
    audio_codec   VARCHAR(20),
    sample_rate   INTEGER,
    duration_ms   INTEGER,
    answered_at   DATETIME    NOT NULL,
    is_active     BOOLEAN     NOT NULL DEFAULT 1
)
"""

# 계약상 questionKey <-> 내부 questions 행 / 태그 분류 매핑
_VOICE_QUESTIONS_DDL = """
CREATE TABLE IF NOT EXISTS voice_questions (
    question_key  VARCHAR(2)  PRIMARY KEY,
    question_id   INTEGER     NOT NULL REFERENCES questions(id),
    tag_category  VARCHAR(4)  NOT NULL,
    polarity      VARCHAR(10) NOT NULL,
    sort_order    INTEGER     NOT NULL,
    prompt_text   TEXT        NOT NULL
)
"""

# 기존 테이블에 없어서 추가해야 하는 컬럼들 (테이블 -> [(컬럼, 정의)])
_ADDED_COLUMNS = {
    "sessions": [
        ("last_activity_at", "DATETIME"),
        ("expires_at", "DATETIME"),
        # 2026-08-26: 프런트 보안 리뷰(세션이 "시작으로 돌아가기" 후에도 재사용되는 문제)
        # 대응 — 명시적으로 끝난 세션을 유휴/최대TTL 만료를 기다리지 않고 즉시 무효화하기
        # 위한 컬럼. ended_at이 채워지면 is_expired()가 무조건 True를 반환한다.
        ("ended_at", "DATETIME"),
    ],
    "session_recommendations": [
        ("reason_text", "TEXT"),
        ("matched_keywords", "TEXT"),
        ("created_at", "DATETIME"),
    ],
}


def ensure_voice_schema() -> None:
    """음성 흐름에 필요한 테이블/컬럼/기준 데이터를 보정한다. 여러 번 호출해도 안전하다.

    Render 무료 플랜은 파일시스템이 비영속이라 배포/재시작마다 커밋된 job.db가
    다시 펼쳐진다. 그래서 별도 마이그레이션 명령에 의존하지 않고 앱 시작 시 호출한다.
    """
    with get_db() as db:
        db.execute(_VOICE_ANSWERS_DDL)
        db.execute(
            "CREATE INDEX IF NOT EXISTS idx_voice_answers_session "
            "ON session_voice_answers(session_id, question_key)"
        )
        db.execute(_VOICE_QUESTIONS_DDL)

        for table, columns in _ADDED_COLUMNS.items():
            existing = {r["name"] for r in db.execute("PRAGMA table_info(%s)" % table)}
            for name, ddl in columns:
                if name not in existing:
                    db.execute("ALTER TABLE %s ADD COLUMN %s %s" % (table, name, ddl))

        _seed_cert_tags(db)
        _seed_voice_questions(db)

        # KNOW 82축 벡터 + barrier 제외를 채워서 D/E/F 추천이 27개가 아니라 538개
        # 전체 직무를 후보로 쓰게 한다(voice_engine.py, skillmatch-voice-backend에서 이식).
        from voice_engine import ensure_voice_engine_data

        ensure_voice_engine_data(db)


def _seed_cert_tags(db) -> None:
    """G(자격증) 답변을 담을 CERT 분류 태그를 채운다."""
    for code, label, description in CERT_TAGS:
        db.execute(
            "INSERT OR IGNORE INTO tags (code, category, label, description) "
            "VALUES (?, 'CERT', ?, ?)",
            (code, label, description),
        )


def _seed_voice_questions(db) -> None:
    """음성 5문항을 questions에 만들고 voice_questions 매핑과 선택지를 채운다.

    기존 questions 행(B/D/E/F)은 질문 내용이 프론트 5문항과 달라서 재사용하지 않고
    Q_VOICE_* 코드로 별도 행을 만든다. 조회는 step이 아니라 voice_questions를 거친다.
    """
    for question_key, tag_category, polarity, sort_order, prompt_text in VOICE_QUESTIONS:
        code = "Q_VOICE_%s" % question_key
        db.execute(
            "INSERT OR IGNORE INTO questions "
            "(code, step, text, applies_to, is_multi_select, sort_order) "
            "VALUES (?, ?, ?, NULL, 1, ?)",
            (code, question_key, prompt_text, 100 + sort_order),
        )
        question_id = db.execute(
            "SELECT id FROM questions WHERE code = ?", (code,)
        ).fetchone()["id"]

        db.execute(
            "INSERT OR REPLACE INTO voice_questions "
            "(question_key, question_id, tag_category, polarity, sort_order, prompt_text) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (question_key, question_id, tag_category, polarity, sort_order, prompt_text),
        )

        # 감지된 태그를 session_answers에도 남기려면 질문마다 선택지 행이 있어야 한다.
        # 해당 분류의 태그 하나당 선택지 하나를 만든다.
        existing = {
            r["tag_id"]
            for r in db.execute(
                "SELECT tag_id FROM question_options WHERE question_id = ?", (question_id,)
            )
        }
        tags = db.execute(
            "SELECT id, label FROM tags WHERE category = ? ORDER BY id", (tag_category,)
        ).fetchall()
        for order, tag in enumerate(tags):
            if tag["id"] in existing:
                continue
            db.execute(
                "INSERT INTO question_options "
                "(question_id, label, tag_id, is_skip, sort_order) VALUES (?, ?, ?, 0, ?)",
                (question_id, tag["label"], tag["id"], order),
            )


# --- 세션 -----------------------------------------------------------------


def create_session(device_hash: Optional[str] = None) -> Dict:
    now = utcnow()
    expires_at = now + timedelta(seconds=MAX_TTL_SECONDS)
    session_id = str(uuid.uuid4())
    with get_db() as db:
        # 새 세션을 만들 때마다 오래전에 만료된 세션(+답변·추천)을 정리한다. 백그라운드
        # 스케줄러 없이도 "민감한 전사문을 무기한 보관하지 않는다"는 최소한의 보증을 준다
        # (프런트 보안 리뷰의 retention 권고 대응). 만료 직후 세션을 바로 지우면 정상적인
        # SESSION_EXPIRED(410) 오류 경로와 겹칠 수 있어서, 유예 기간을 두고 그 이후만 지운다.
        _sweep_expired_sessions(db)
        db.execute(
            """
            INSERT INTO sessions (
                id, started_at, revision_count, staff_help_requested,
                device_hash, last_activity_at, expires_at
            ) VALUES (?, ?, 0, 0, ?, ?, ?)
            """,
            (
                session_id,
                to_sql(now),
                device_hash,
                to_sql(now),
                to_sql(expires_at),
            ),
        )
    return {"id": session_id, "started_at": now, "expires_at": expires_at}


def get_session(session_id: str) -> Optional[Dict]:
    with get_db() as db:
        row = db.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
    return dict(row) if row else None


def is_expired(session: Dict, now: Optional[datetime] = None) -> bool:
    """유휴 시간 초과(마지막 활동 기준), 최대 수명 초과, 또는 명시적으로 끝난 세션이면 만료."""
    if session.get("ended_at"):
        return True
    now = now or utcnow()
    started = from_sql(session["started_at"])
    if now >= started + timedelta(seconds=MAX_TTL_SECONDS):
        return True
    last = session.get("last_activity_at") or session["started_at"]
    return now >= from_sql(last) + timedelta(seconds=IDLE_TIMEOUT_SECONDS)


def end_session(session_id: str) -> None:
    """세션을 즉시 무효화한다(유휴/최대TTL 만료를 기다리지 않음).

    프런트가 "상담 취소" 또는 "시작 화면으로 돌아가기" 시점에 호출해서, 같은 sessionId가
    유휴 타임아웃(최대 120초)이 끝나기 전까지 재사용 가능한 채로 남아있는 창을 없앤다
    (보안 리뷰 Finding — 세션이 다음 사용자에게 그대로 넘어가는 문제의 백엔드 측 대응).
    이미 없거나 이미 끝난 세션에 대해 호출해도 안전하다(멱등).
    """
    with get_db() as db:
        db.execute(
            "UPDATE sessions SET ended_at = ? WHERE id = ? AND ended_at IS NULL",
            (to_sql(utcnow()), session_id),
        )


# 만료 후 이 시간(초)이 더 지나야 실제로 지운다 — 그 사이엔 클라이언트가 SESSION_EXPIRED
# 응답을 정상적으로 받을 수 있어야 하므로, 만료 즉시 삭제하지 않는다.
RETENTION_GRACE_SECONDS = 3600


_STALE_SESSION_IDS_SQL = """
    SELECT id FROM sessions
     WHERE (ended_at IS NOT NULL AND ended_at < ?)
        OR (expires_at IS NOT NULL AND expires_at < ?)
"""


def _sweep_expired_sessions(db) -> int:
    """만료(또는 명시적 종료)된 지 RETENTION_GRACE_SECONDS 이상 지난 세션과 그 답변·추천을
    지운다. FK cascade 여부가 불확실해서 자식 테이블부터 명시적으로 지운다.

    2026-08-26 QA 수정(Claude Code): 처음엔 대상 id를 파이썬으로 모아서
    `WHERE id IN (?,?,?...)`로 지웠는데, 쌓인 만료 세션이 SQLite 바인드 파라미터 상한
    (많은 빌드에서 999개)을 넘으면 "too many SQL variables"로 예외가 나고, 이게
    create_session() 안에서 통째로 터져서 세션 생성 자체가 막힌다 — 정리 루틴 하나 때문에
    전체 서비스가 멈추는 셈. 그래서 id를 파이썬으로 들고 다니지 않고 서브쿼리로 바로
    지운다 — 몇 개가 지워지든 바인드 파라미터는 쿼리당 2개(컷오프 두 번)로 고정된다.
    """
    cutoff = to_sql(utcnow() - timedelta(seconds=RETENTION_GRACE_SECONDS))
    params = (cutoff, cutoff)

    for table in ("session_recommendations", "session_answers", "session_voice_answers"):
        db.execute(
            f"DELETE FROM {table} WHERE session_id IN ({_STALE_SESSION_IDS_SQL})", params
        )
    cursor = db.execute(f"DELETE FROM sessions WHERE id IN ({_STALE_SESSION_IDS_SQL})", params)
    return cursor.rowcount if cursor.rowcount is not None and cursor.rowcount >= 0 else 0


def touch_session(session_id: str, last_step: Optional[str] = None) -> None:
    now = utcnow()
    with get_db() as db:
        if last_step:
            db.execute(
                "UPDATE sessions SET last_activity_at = ?, last_step = ? WHERE id = ?",
                (to_sql(now), last_step, session_id),
            )
        else:
            db.execute(
                "UPDATE sessions SET last_activity_at = ? WHERE id = ?",
                (to_sql(now), session_id),
            )


# --- 질문 / 태그 ----------------------------------------------------------


def voice_question(question_key: str) -> Optional[Dict]:
    """계약상 questionKey에 대응하는 내부 질문/태그 분류."""
    with get_db() as db:
        row = db.execute(
            "SELECT question_key, question_id, tag_category, polarity, prompt_text "
            "FROM voice_questions WHERE question_key = ?",
            (question_key,),
        ).fetchone()
    return dict(row) if row else None


def tags_by_category(category: str) -> List[Dict]:
    with get_db() as db:
        rows = db.execute(
            "SELECT id, code, category, label, description FROM tags "
            "WHERE category = ? ORDER BY id",
            (category,),
        ).fetchall()
    return [dict(r) for r in rows]


def options_for_question(question_id: int) -> List[Dict]:
    """질문에 달린 선택지 + 연결된 태그. 음성 답변을 기존 선택지에 매핑할 때 쓴다."""
    with get_db() as db:
        rows = db.execute(
            """
            SELECT o.id, o.question_id, o.label, o.tag_id, o.is_skip, t.code AS tag_code
            FROM question_options o
            LEFT JOIN tags t ON t.id = o.tag_id
            WHERE o.question_id = ?
            ORDER BY o.sort_order
            """,
            (question_id,),
        ).fetchall()
    return [dict(r) for r in rows]


# --- 음성 답변 저장 --------------------------------------------------------


def save_voice_answer(
    session_id: str,
    question_key: str,
    stt_text: str,
    keywords: List[str],
    confidence: Optional[float],
    audio_meta: Dict,
    option_ids: List[int],
    question_id: Optional[int],
) -> datetime:
    """음성 답변 원본을 저장하고, 매칭된 선택지는 session_answers에도 반영한다.

    같은 questionKey를 다시 답하면 이전 답변은 비활성으로 돌리고 revision_count를 올린다.
    """
    now = utcnow()
    with get_db() as db:
        previous = db.execute(
            "SELECT COUNT(*) AS n FROM session_voice_answers "
            "WHERE session_id = ? AND question_key = ? AND is_active = 1",
            (session_id, question_key),
        ).fetchone()["n"]
        is_revision = 1 if previous else 0

        if previous:
            db.execute(
                "UPDATE session_voice_answers SET is_active = 0 "
                "WHERE session_id = ? AND question_key = ?",
                (session_id, question_key),
            )
            if question_id is not None:
                db.execute(
                    "UPDATE session_answers SET is_active = 0 "
                    "WHERE session_id = ? AND question_id = ?",
                    (session_id, question_id),
                )
            db.execute(
                "UPDATE sessions SET revision_count = revision_count + 1 WHERE id = ?",
                (session_id,),
            )

        db.execute(
            """
            INSERT INTO session_voice_answers (
                session_id, question_key, stt_text, keywords, confidence,
                audio_format, audio_codec, sample_rate, duration_ms, answered_at, is_active
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
            """,
            (
                session_id,
                question_key,
                stt_text,
                json.dumps(keywords, ensure_ascii=False),
                confidence,
                audio_meta.get("format"),
                audio_meta.get("codec"),
                audio_meta.get("sampleRate"),
                audio_meta.get("durationMs"),
                to_sql(now),
            ),
        )

        for option_id in option_ids:
            db.execute(
                """
                INSERT INTO session_answers (
                    session_id, question_id, option_id, answered_at, is_revision, is_active
                ) VALUES (?, ?, ?, ?, ?, 1)
                """,
                (session_id, question_id, option_id, to_sql(now), is_revision),
            )
    return now


def active_voice_answers(session_id: str) -> Dict[str, Dict]:
    """questionKey -> 현재 유효한 음성 답변."""
    with get_db() as db:
        rows = db.execute(
            "SELECT question_key, stt_text, keywords, confidence, answered_at "
            "FROM session_voice_answers WHERE session_id = ? AND is_active = 1 "
            "ORDER BY id",
            (session_id,),
        ).fetchall()
    answers = {}
    for row in rows:
        item = dict(row)
        item["keywords"] = json.loads(item["keywords"] or "[]")
        answers[item["question_key"]] = item
    return answers


# --- 추천 -----------------------------------------------------------------


def all_tag_labels() -> Dict[str, str]:
    with get_db() as db:
        rows = db.execute("SELECT code, label FROM tags").fetchall()
    return {r["code"]: r["label"] for r in rows}


def recommendable_job_tags() -> List[Dict]:
    """추천 대상 직업에 붙은 태그 전체(job_tags, REQUIRED/BONUS/EXCLUDE_IF_DIFFICULT).

    2026-08-26: voice.py의 추천 채점이 이제 KNOW 82축 엔진(voice_engine.score_and_rank)을
    쓰기 때문에 이 함수는 더 이상 호출되지 않는다. job_tags 테이블 자체(27개 직업 수작업
    태그)는 그대로 남아 있으니, 나중에 이 정밀 태그를 다시 참고하고 싶으면 여기서 시작하면
    된다 — 지워도 되는 죽은 코드는 아니고, "현재 안 쓰인다"는 뜻이다.
    """
    with get_db() as db:
        rows = db.execute(
            """
            SELECT jt.job_id, jt.role, jt.weight, t.code AS tag_code
            FROM job_tags jt
            JOIN tags t ON t.id = jt.tag_id
            JOIN jobs j ON j.id = jt.job_id
            WHERE j.is_recommendable = 1
            """
        ).fetchall()
    return [dict(r) for r in rows]


def jobs_requiring_cert() -> set:
    """추천 후보(538개, is_voice_recommendable) 중 자격증이 필요한 직업 id.

    G 답변으로 걸러낼 때 쓴다. 주의: requires_cert는 기존 27개 파일럿 직업(4건) +
    2026-08-26에 실데이터 기반으로 추가로 채운 8건(사회복지사·보육교사·이용사·미용사·
    사서·청소년지도사·부동산중개인·간호조무사) — 총 12건만 사람이 채운 값이다. 새로
    편입된 나머지 ~500여 개는 실제로 자격증이 필요해도 여기 걸리지 않는다 — 계속
    데이터 갱신이 필요한 알려진 한계다.
    """
    with get_db() as db:
        rows = db.execute(
            "SELECT id FROM jobs WHERE is_voice_recommendable = 1 AND requires_cert = 1"
        ).fetchall()
    return {r["id"] for r in rows}


def fetch_jobs(job_ids: List[int]) -> Dict[int, Dict]:
    """/api/jobs와 같은 필드 구성으로 직업을 가져온다. id -> dict."""
    if not job_ids:
        return {}
    placeholders = ",".join("?" for _ in job_ids)
    with get_db() as db:
        rows = db.execute(
            JOBS_SQL + " WHERE j.id IN (%s)" % placeholders, job_ids
        ).fetchall()
    return {r["id"]: dict(r) for r in rows}


def fallback_job_ids(limit: int) -> List[int]:
    """태그 매칭이 하나도 안 될 때 보여줄 기본 추천(자격증 불필요한 직업 우선)."""
    with get_db() as db:
        rows = db.execute(
            "SELECT id FROM jobs WHERE is_voice_recommendable = 1 "
            "ORDER BY requires_cert, id LIMIT ?",
            (limit,),
        ).fetchall()
    return [r["id"] for r in rows]


def save_recommendations(session_id: str, items: List[Dict], is_fallback: bool) -> datetime:
    """추천 결과를 session_recommendations에 다시 쓴다(같은 세션은 덮어쓴다).

    rank는 1부터 items 개수만큼. session_recommendations에는 rank 상한 CHECK가 없어
    1~5도 그대로 저장된다(UNIQUE(session_id, rank)만 걸려 있다).
    """
    now = utcnow()
    with get_db() as db:
        db.execute("DELETE FROM session_recommendations WHERE session_id = ?", (session_id,))
        for rank, item in enumerate(items, start=1):
            db.execute(
                """
                INSERT INTO session_recommendations (
                    session_id, job_id, rank, score, is_fallback,
                    reason_text, matched_keywords, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    item["id"],
                    rank,
                    # 2026-08-26: 82축 코사인 유사도는 0~1 소수라 int()로 자르면 전부
                    # 0이 돼버린다(기존 job_tags 정수 가중치 스코어 시절 코드). float로 저장.
                    float(item.get("score", 0)),
                    1 if is_fallback else 0,
                    item.get("reason"),
                    json.dumps(item.get("matchedKeywords", []), ensure_ascii=False),
                    to_sql(now),
                ),
            )
        db.execute(
            "UPDATE sessions SET completed_at = ?, last_activity_at = ?, last_step = 'G' "
            "WHERE id = ?",
            (to_sql(now), to_sql(now), session_id),
        )
    return now
