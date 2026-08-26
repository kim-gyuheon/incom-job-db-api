"""538개 직무 전체를 대상으로 한 KNOW 82축 코사인 유사도 매칭 엔진 어댑터.

기존 voice.py의 `_score_jobs()`는 job_tags(수작업 태그 27개 직업)로 점수를 매겼는데,
이 모듈은 그 자리를 대신해서 skillmatch-voice-backend에서 검증된 82축 매칭 엔진 +
barrier 하드필터를 SQLite job.db(538개 직무 전체)에 이식한다.

원본 엔진(`engine/`, `tagging.py`, `vectorizing.py`)은 수정 없이 그대로 가져왔고, 이
모듈은 그 위에 "job.db의 jobs.id <-> 82축 CSV/barrier CSV의 job_name" 크로스워크만
새로 얹는다. 두 데이터셋의 직업명 538개가 정확히 1:1로 일치함을 사전에 확인했다
(교집합 538/538).

부팅마다(Render 무료 플랜은 배포마다 job.db가 초기화되므로) `ensure_voice_engine_data()`를
호출해 벡터/장벽 테이블을 다시 채운다 — CSV 538행을 SQLite에 쓰는 정도라 수백 ms면 끝난다.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np

ROOT_DIR = Path(__file__).resolve().parents[1]
ENGINE_DIR = ROOT_DIR / "engine"
if str(ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(ENGINE_DIR))

from career_config import JobSourceConfig  # type: ignore  # noqa: E402
from job_repository import FileCatalogSource, get_job_catalog  # type: ignore  # noqa: E402
from matching_engine import recommend as engine_recommend  # type: ignore  # noqa: E402

from tagging import TagMatch, extract_tags  # type: ignore  # noqa: E402
from vectorizing import vectorize_tags  # type: ignore  # noqa: E402

JOB_SCORE_PATH = ROOT_DIR / "data" / "job-scores" / "직무역량_KNOW_82축.csv"
BARRIER_PATH = ROOT_DIR / "data" / "barrier-review-combined.csv"

# 2026-08-26: 82축 코사인 유사도는 "지식/성격" 방향의 유사성만 보고 "자격을 딸 수 있는가"는
# 전혀 반영하지 않는다. 실측 결과, "돌봄" 경험(caregiving) 답변의 추천 top5 중 4개가
# 안과의사/이비인후과의사 등 전문의였다(의료 지식 축을 공유해서 유사도가 높게 나옴) —
# 실제로는 자격 자체가 완전히 다른 직업이라 그대로 두면 위험하다. 자격증/시험/학위로
# 진입이 막혀 있고 이 키오스크의 음성 상담만으로 도달할 수 없는 직군은 크로스워크는
# 되더라도 is_voice_recommendable에서 다시 뺀다.
#
# cat1/cat2 단위로 통째로 뺀 카테고리(보수적으로 넓게 잡음 — 그 안의 일부는 실제로 접근
# 가능할 수 있으나, 이번 1차 조치에서는 안전 쪽으로 기움):
EXCLUDED_CATEGORY_LEVELS: Dict[str, set] = {
    "cat2": {
        "관리직(임원·부서장)",   # 임원·고위공무원 — 경력 승진의 결과지 채용 경로가 아님
        "법률직",                # 판사/검사/변호사/변리사 — 사법시험·변호사시험 필요
        "경찰·소방·교도직",       # 공채 시험 + 체력 검정 필요
        "군인",                  # 입대 절차, 이 앱의 취업상담 성격과 안 맞음
        "교육직",                # 교원자격증 필요(대학교수~유치원교사 전부)
    },
    "cat1": {
        "연구직 및 공학 기술직",  # ~기술자/~연구원 대부분 4년제 이공계 학위 전제
        "보건·의료직",            # 의사/약사/치과의사/한의사/수의사 + 임상병리사 등
                                  # 의료기사 전부 국가 면허 필요(간호조무사도 함께 빠짐 —
                                  # 별도로 접근 가능하다고 판단되면 예외로 다시 넣을 것)
    },
}

# 위 카테고리 필터로 못 잡는 개별 직업 — "경영·행정·사무직"/"금융·보험직" cat2는 대부분
# 접근 가능한 사무직(회계사무원, 은행사무원 등)이라 카테고리째 빼지 않았는데, 그 안에
# 국가자격시험이 필요한 전문직이 몇 개 섞여 있다. 실제로 "관세사"가 새어나온 걸 확인해서
# 추가함 — 같은 성격(시험 합격 필요)의 나머지도 함께 뺐다. 조종사/관제사는 면허 등급.
EXCLUDED_JOB_NAMES: set = {
    "항공기조종사", "헬리콥터조종사", "선장 및 항해사",
    "철도·전동차기관사", "항공교통관제사", "선박교통관제사",
    # 국가자격시험(회계사·세무사급) 필요 전문직 — "경영·행정·사무직" cat2 안에 섞여 있음.
    "노무사", "회계사", "세무사", "관세사", "감정평가사", "행정사",
    # 손해사정사도 국가자격시험 필요 — "금융·보험직" cat2 안에 섞여 있음.
    "손해사정사",
    # 공무원 임용시험(경쟁 채용) 필요 — 경찰·소방·교도직과 같은 성격의 진입장벽.
    "조세행정사무원", "관세행정사무원", "병무행정사무원", "일반행정공무원", "법원공무원",
}

# 2026-08-26: 반대 방향(과잉 제외) 1차 세분화 — cat1/cat2를 통째로 뺐을 때 같이 빠진
# 개별 직업 중, 그 카테고리의 대표 자격(변호사시험/의사면허/4년제 이공계 학위 등)이
# 아니라 국가자격시험 하나로 취득 가능해서 실제로는 접근 가능한 직업만 다시 넣는다.
# (요양보호사·경비원처럼 이 앱에 이미 있는 "자격증은 있지만 시험으로 취득 가능한" 직업과
# 같은 성격 — requires_cert=1 + cert_note로 자격 필요 사실은 그대로 안내한다.)
ALLOWED_EXCEPTIONS: set = {
    "법률사무원",  # 법률직 cat2 전체 제외에 같이 빠짐 — 변호사시험이 아니라 법률사무소
                  # 사무보조 업무라 접근 가능한 사무직에 가까움 (requires_cert=0)
    "간호조무사",  # 보건·의료직 cat1 전체 제외에 같이 빠짐 — 간호조무사 국가시험(학위
                  # 불필요)으로 취득 가능해서 요양보호사와 같은 성격 (requires_cert=1)
}

# 2026-08-26: 위 주석(과거)은 barrier 태그(tag-keyword-dictionary.json, 16개)와
# barrier-review-combined.csv의 barrier_id(12개)가 같은 어휘라고 적어놨었는데 실제로는
# 아니었다 — 페르소나 테스트로 발견: 이름이 정확히 겹치는 3개(lift_heavy/stand_long/
# night_shift)만 실제로 제외가 걸리고, 나머지 13개는 barrier_id 자체가 다르게 불려서
# voice_job_barrier_excludes 조회에서 단 하나도 안 걸렸다(예: computer_work으로 추출된
# 태그가 실제로는 CSV의 computer_use라는 이름으로 241개 직업 제외 데이터를 갖고 있는데,
# 이름이 안 맞아서 그 데이터가 통째로 무시됨). 아래 매핑으로 이름을 맞춰서 살린다.
# CSV 쪽에 대응 항목 자체가 없는 5개(walk_long/bend_often/fast_pace/cold_hot_env/
# customer_conflict — customer_conflict는 customer_facing으로 근사 매핑)는 여전히 실제
# 제외 데이터가 없어서 매핑해도 효과가 없다 — barrier-review 데이터 자체를 새로 만들어야
# 하는 후속 과제.
BARRIER_ID_ALIASES: Dict[str, str] = {
    "customer_contact_avoid": "customer_facing",
    "customer_conflict": "customer_facing",  # CSV에 정확히 대응하는 항목이 없어 근사 매핑
    "fine_hand_work": "fine_hand",
    "computer_work": "computer_use",
    "outdoor_avoid": "outdoor",
    "height_avoid": "high_place",
    "public_speaking_avoid": "speak_public",
    "drive_avoid": "drive_vehicle",
    "early_morning_avoid": "early_morning",
}


def _to_csv_barrier_ids(barrier_tag_ids: set) -> set:
    """우리 태그사전 barrier_id를 barrier-review-combined.csv의 barrier_id로 변환한다.

    매핑에 없는 건(lift_heavy/stand_long/night_shift처럼 원래 이름이 같은 것 포함) 그대로
    통과시킨다 — BARRIER_ID_ALIASES.get(x, x).
    """
    return {BARRIER_ID_ALIASES.get(bid, bid) for bid in barrier_tag_ids}


def _catalog_source() -> FileCatalogSource:
    cfg = JobSourceConfig(path=str(JOB_SCORE_PATH))
    return FileCatalogSource(source_cfg=cfg, barrier_path=str(BARRIER_PATH))


_VOICE_SCHEMA_DDL = [
    """
    CREATE TABLE IF NOT EXISTS voice_job_axis_vectors (
        job_id      INTEGER PRIMARY KEY REFERENCES jobs(id) ON DELETE CASCADE,
        vector_json TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS voice_job_barrier_excludes (
        job_id     INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
        barrier_id TEXT    NOT NULL,
        PRIMARY KEY (job_id, barrier_id)
    )
    """,
]


def ensure_voice_engine_data(db) -> None:
    """82축 벡터 + barrier 제외 테이블을 채운다. 여러 번 불러도 안전(전부 지우고 다시 씀).

    job.db의 `jobs.name`과 82축 CSV/barrier CSV의 직업명이 538개 전부 1:1로 일치한다는
    전제로 이름 매칭을 쓴다(사전 검증 완료). 이름이 안 겹치는 직업은 조용히 건너뛴다 —
    나중에 koeco 데이터가 갱신돼서 명칭이 달라지면 여기서 매칭이 빠지는 식으로 드러난다.
    """
    for ddl in _VOICE_SCHEMA_DDL:
        db.execute(ddl)
    if not _has_column(db, "jobs", "is_voice_recommendable"):
        db.execute(
            "ALTER TABLE jobs ADD COLUMN is_voice_recommendable INTEGER NOT NULL DEFAULT 0"
        )

    name_to_id = {
        row["name"]: row["id"] for row in db.execute("SELECT id, name FROM jobs")
    }

    catalog = get_job_catalog(source=_catalog_source(), refresh=True)
    # catalog.excludes[idx]는 FileCatalogSource가 barrier-review-combined.csv를 이미
    # job_name 기준으로 82축 job_id(J01-001 형식)에 매핑해서 만들어 둔 제외 태그 집합이다
    # (job_repository.FileCatalogSource.load_catalog 참고) — 여기서 다시 조인할 필요 없음.

    db.execute("DELETE FROM voice_job_axis_vectors")
    db.execute("DELETE FROM voice_job_barrier_excludes")
    db.execute("UPDATE jobs SET is_voice_recommendable = 0")

    matched = 0
    for idx in range(len(catalog)):
        job_name = catalog.job_names[idx]
        job_id = name_to_id.get(job_name)
        if job_id is None:
            continue
        vector = catalog.vectors[idx].tolist()
        db.execute(
            "INSERT INTO voice_job_axis_vectors (job_id, vector_json) VALUES (?, ?)",
            (job_id, json.dumps(vector)),
        )
        for barrier_id in catalog.excludes[idx]:
            db.execute(
                "INSERT OR IGNORE INTO voice_job_barrier_excludes (job_id, barrier_id) "
                "VALUES (?, ?)",
                (job_id, barrier_id),
            )
        db.execute("UPDATE jobs SET is_voice_recommendable = 1 WHERE id = ?", (job_id,))
        matched += 1

    if matched == 0:
        raise RuntimeError(
            "voice_engine: job.db의 jobs.name과 82축 CSV 직업명이 하나도 안 겹칩니다. "
            "koeco 데이터 갱신으로 명칭이 바뀌었을 수 있습니다."
        )

    excluded = _exclude_credential_gated_jobs(db)
    return excluded


def _exclude_credential_gated_jobs(db) -> int:
    """자격증/시험/학위로 진입이 막힌 직군을 is_voice_recommendable에서 다시 뺀다.

    EXCLUDED_CATEGORY_LEVELS/EXCLUDED_JOB_NAMES 참고 — 왜 이게 필요한지는 그 위 주석에
    적어 둔 실측 사례(돌봄 답변 -> 전문의 추천)를 보면 된다. 보수적으로 넓게 잡은
    1차 조치라 일부 과잉 제외가 있었는데, ALLOWED_EXCEPTIONS로 그중 확인된 2건(법률
    사무원·간호조무사)만 되돌렸다 — 202개 제외 대상 전체를 개별 심사한 건 아니라서
    나머지 중에도 과잉 제외가 남아 있을 수 있다. 반대 방향(비제외 카테고리 안에 숨은
    자격증 필요 직업)도 8건만 확인해서 requires_cert를 채웠고 전수 조사는 아니다 —
    두 방향 모두 후속 과제로 남는다.
    """
    rows = db.execute(
        """
        SELECT j.id AS id, j.name AS name, c1.name AS cat1, c2.name AS cat2
          FROM jobs j
          JOIN job_categories c3 ON c3.id = j.category_id
          JOIN job_categories c2 ON c2.id = c3.parent_id
          JOIN job_categories c1 ON c1.id = c2.parent_id
         WHERE j.is_voice_recommendable = 1
        """
    ).fetchall()

    to_exclude = [
        r["id"]
        for r in rows
        if r["name"] not in ALLOWED_EXCEPTIONS
        and (
            r["cat1"] in EXCLUDED_CATEGORY_LEVELS["cat1"]
            or r["cat2"] in EXCLUDED_CATEGORY_LEVELS["cat2"]
            or r["name"] in EXCLUDED_JOB_NAMES
        )
    ]
    for job_id in to_exclude:
        db.execute("UPDATE jobs SET is_voice_recommendable = 0 WHERE id = ?", (job_id,))
    return len(to_exclude)


def _has_column(db, table: str, column: str) -> bool:
    return column in {r["name"] for r in db.execute("PRAGMA table_info(%s)" % table)}


# --- 태그 추출 (D/E/F/C 공용, 규칙 기반 정규식 — LLM 불필요) --------------------


def extract_positive_and_barrier(text: str) -> Tuple[List[TagMatch], List[TagMatch]]:
    """텍스트에서 (긍정 신호 태그, barrier 태그)를 함께 뽑는다.

    tagging.extract_tags()는 질문 구분 없이 전체 어휘를 한 번에 스캔한다(부정어 처리 포함).
    positive = experience/condition 카테고리, barrier = barrier 카테고리.
    """
    matches = extract_tags(text)
    positive = [m for m in matches if m.category in ("experience", "condition")]
    barrier = [m for m in matches if m.category == "barrier"]
    return positive, barrier


# --- 추천 -------------------------------------------------------------------

# 2026-08-26: 82축 코사인 유사도가 후보 전체(320여 개)에서 0.80~0.99 구간에 뭉쳐서
# 구별력이 약하다는 걸 페르소나 테스트로 확인함(예: 순수 사무 경력 하나만 줘도 top5의
# 절반이 사무직과 무관한 업종). 원본 엔진(engine/matching_engine.py)은 손대지 않고,
# recommend()가 이미 제공하는 adjust 콜백으로 "실제로 답변에서 매칭된 경험 태그의
# 업종과 후보의 KECO 카테고리가 겹치면" 유사도에 소폭 가산점을 준다 — 완전 재설계
# 없이 순위만 다듬는 최소 침습적 조치. 프론트엔드 응답 스키마는 그대로다.
EXPERIENCE_CATEGORY_BOOST: Dict[str, tuple] = {
    "food_service": ("음식 서비스직",),
    "cleaning": ("청소 및 기타 개인서비스직",),
    "security": ("경호·경비직",),
    "caregiving": ("청소 및 기타 개인서비스직",),  # 요양보호사·간병인이 이 cat2에 있음
    "driving_delivery": ("운전·운송직",),
    "retail_sales": ("영업·판매직",),
    "factory_light": ("설치·정비·생산직",),
    "farming": ("농림어업직",),
    "office_admin": ("경영·행정·사무직",),
    "childcare": ("보육", "육아"),
    "tech_office_ok": ("경영·행정·사무직",),  # condition 태그지만 사무직과 직결
}
CATEGORY_BOOST_AMOUNT = 0.05


def _category_boost_lookup(db, job_ids: List[int]) -> Dict[int, str]:
    """job_id -> "cat1 cat2 cat3" 합친 문자열(부분일치 검사용)."""
    if not job_ids:
        return {}
    placeholders = ",".join("?" for _ in job_ids)
    rows = db.execute(
        f"""
        SELECT j.id AS id, c1.name AS cat1, c2.name AS cat2, c3.name AS cat3
          FROM jobs j
          JOIN job_categories c3 ON c3.id = j.category_id
          JOIN job_categories c2 ON c2.id = c3.parent_id
          JOIN job_categories c1 ON c1.id = c2.parent_id
         WHERE j.id IN ({placeholders})
        """,
        job_ids,
    ).fetchall()
    return {r["id"]: f"{r['cat1']} {r['cat2']} {r['cat3']}" for r in rows}


def _make_category_boost_adjuster(
    positive_matches: List[TagMatch], category_by_id: Dict[int, str]
):
    """매칭된 경험 태그의 업종과 후보 카테고리가 겹치면 가산점을 주는 adjust 콜백."""
    boost_terms = set()
    for m in positive_matches:
        boost_terms.update(EXPERIENCE_CATEGORY_BOOST.get(m.tag_id, ()))
    if not boost_terms:
        return None

    def adjust(similarities: np.ndarray, job_ids) -> np.ndarray:
        adjusted = similarities.copy()
        for i, jid in enumerate(job_ids):
            category_text = category_by_id.get(jid, "")
            if any(term in category_text for term in boost_terms):
                adjusted[i] += CATEGORY_BOOST_AMOUNT
        return adjusted

    return adjust


def score_and_rank(
    db,
    positive_matches: List[TagMatch],
    barrier_tag_ids: set,
    cert_required_job_ids: set,
    top_k: int = 5,
) -> Tuple[List[Dict], bool]:
    """82축 코사인 유사도로 상위 top_k 직무를 뽑는다.

    반환: (스코어링된 항목 리스트[{job_id, score, matchedKeywords}], is_fallback)
    """
    rows = db.execute(
        "SELECT job_id, vector_json FROM voice_job_axis_vectors "
        "WHERE job_id IN (SELECT id FROM jobs WHERE is_voice_recommendable = 1)"
    ).fetchall()
    if not rows:
        return [], True

    job_ids = [r["job_id"] for r in rows]
    vectors = np.array([json.loads(r["vector_json"]) for r in rows], dtype=float)

    if barrier_tag_ids:
        csv_barrier_ids = _to_csv_barrier_ids(barrier_tag_ids)
        excluded = {
            r["job_id"]
            for r in db.execute(
                "SELECT DISTINCT job_id FROM voice_job_barrier_excludes "
                "WHERE barrier_id IN (%s)" % ",".join("?" for _ in csv_barrier_ids),
                tuple(csv_barrier_ids),
            )
        }
    else:
        excluded = set()
    excluded |= cert_required_job_ids

    keep_idx = [i for i, jid in enumerate(job_ids) if jid not in excluded]
    if not keep_idx:
        return [], True

    kept_ids = [job_ids[i] for i in keep_idx]
    kept_vectors = vectors[keep_idx]

    user_vector = vectorize_tags(positive_matches)
    if np.linalg.norm(user_vector) == 0:
        # 긍정 신호가 하나도 안 잡힘 — 코사인 유사도 계산이 불가능하므로 폴백으로 넘긴다.
        return [], True

    category_by_id = _category_boost_lookup(db, kept_ids)
    adjust = _make_category_boost_adjuster(positive_matches, category_by_id)
    result = engine_recommend(user_vector, kept_ids, kept_vectors, top_k=top_k, adjust=adjust)

    matched_keywords = list(
        dict.fromkeys(kw for m in positive_matches for kw in m.keywords)
    )
    items = [
        {
            "job_id": item["job_id"],
            "score": item["similarity"],
            "matchedKeywords": matched_keywords,
        }
        for item in result["top_k"]
    ]
    return items, False
