from typing import Dict, List, Optional, Tuple

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

import llm
from db import get_db
from models import (
    AnswerRequest,
    AnswerResponse,
    CategoryItem,
    CategoryListResponse,
    JobItem,
    JobListResponse,
    RecommendationItem,
    RecommendResponse,
    SessionStartResponse,
)

app = FastAPI(title="희망직종 길잡이 API")

app.add_middleware(
    CORSMiddleware,
    # 배포된 프론트엔드(GitHub Pages). Origin에는 저장소 경로(/skillmatchboard/)를 넣지 않는다.
    allow_origins=["https://ymook38897-tech.github.io"],
    # 개발 단계: 팀원이 어느 IP/포트에서 접속해도 막히지 않게 로컬 개발 서버 오리진을 정규식으로 허용.
    # (allow_credentials=True와 allow_origins=["*"]는 함께 쓸 수 없어 regex 병용)
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1|\d+\.\d+\.\d+\.\d+)(:\d+)?",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

MAX_TURNS = 5

# 세션별로 "방금 낸 질문"을 기억해둔다 (답변이 오기 전까지는 아직 conversation_turns에 넣지 않음).
# MVP 단순화: 프로세스 재시작 시 초기화됨. 운영 단계에서는 sessions 테이블 컬럼으로 옮길 것.
_pending: Dict[int, Tuple[int, str]] = {}  # session_id -> (turn_no, question_text)


def _question_hints(db) -> List[Dict]:
    rows = db.execute(
        "SELECT screen, code, label, llm_hint FROM question_options ORDER BY screen, sort_order"
    ).fetchall()
    return [dict(r) for r in rows]


def _session_history(db, session_id: int) -> List[Dict]:
    rows = db.execute(
        "SELECT question_text, user_answer FROM conversation_turns WHERE session_id = ? ORDER BY turn_no",
        (session_id,),
    ).fetchall()
    return [{"question": r["question_text"], "answer": r["user_answer"]} for r in rows]


@app.post("/sessions", response_model=SessionStartResponse)
def start_session():
    with get_db() as db:
        cur = db.execute("INSERT INTO sessions DEFAULT VALUES")
        session_id = cur.lastrowid
        hints = _question_hints(db)

    result = llm.next_turn(hints, history=[], current_question=None, last_answer=None)
    question = result["next_question"]
    _pending[session_id] = (1, question)
    return SessionStartResponse(session_id=session_id, turn_no=1, question_text=question)


@app.post("/sessions/{session_id}/answer", response_model=AnswerResponse)
def submit_answer(session_id: int, body: AnswerRequest):
    pending = _pending.get(session_id)
    if pending is None:
        raise HTTPException(
            status_code=404,
            detail="세션이 없거나 이미 완료되었습니다. 먼저 /sessions로 세션을 시작하세요.",
        )
    turn_no, question_text = pending

    with get_db() as db:
        hints = _question_hints(db)
        history = _session_history(db, session_id)

        result = llm.next_turn(
            hints, history=history, current_question=question_text, last_answer=body.answer
        )

        db.execute(
            "INSERT INTO conversation_turns (session_id, turn_no, question_text, user_answer) "
            "VALUES (?, ?, ?, ?)",
            (session_id, turn_no, question_text, body.answer),
        )
        turn_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]

        valid_codes = {r["code"]: r["id"] for r in db.execute("SELECT id, code FROM question_options")}
        for code in result.get("detected_option_codes", []):
            option_id = valid_codes.get(code)
            if option_id:
                db.execute(
                    "INSERT OR IGNORE INTO turn_detected_options (turn_id, option_id) VALUES (?, ?)",
                    (turn_id, option_id),
                )

        done = bool(result.get("ready_to_recommend")) or turn_no >= MAX_TURNS
        if done:
            del _pending[session_id]
            db.execute("UPDATE sessions SET status = '상담원전달' WHERE id = ?", (session_id,))
            return AnswerResponse(session_id=session_id, turn_no=turn_no, done=True)

        next_turn_no = turn_no + 1
        next_question = result["next_question"]
        _pending[session_id] = (next_turn_no, next_question)
        return AnswerResponse(
            session_id=session_id, turn_no=next_turn_no, done=False, question_text=next_question
        )


@app.post("/sessions/{session_id}/recommend", response_model=RecommendResponse)
def recommend(session_id: int):
    with get_db() as db:
        session_row = db.execute("SELECT id FROM sessions WHERE id = ?", (session_id,)).fetchone()
        if session_row is None:
            raise HTTPException(
                status_code=404,
                detail="존재하지 않는 세션입니다.",
            )

        conversation = _session_history(db, session_id)

        job_categories = [
            dict(r)
            for r in db.execute("SELECT name, easy_description FROM job_categories").fetchall()
        ]

        candidate_jobs = [
            dict(r)
            for r in db.execute(
                """
                SELECT jc.name AS job_category, kj.name AS koeco_job_name,
                       kj.description, kj.avg_salary_band, kj.outlook
                FROM job_category_koeco_jobs j
                JOIN job_categories jc ON jc.id = j.job_category_id
                JOIN koeco_jobs kj ON kj.id = j.koeco_job_id
                """
            ).fetchall()
        ]

        detected_codes = [
            r["code"]
            for r in db.execute(
                """
                SELECT DISTINCT qo.code
                FROM turn_detected_options tdo
                JOIN conversation_turns ct ON ct.id = tdo.turn_id
                JOIN question_options qo ON qo.id = tdo.option_id
                WHERE ct.session_id = ?
                """,
                (session_id,),
            ).fetchall()
        ]

        rule_scores = []
        if detected_codes:
            placeholders = ",".join("?" for _ in detected_codes)
            rule_scores = [
                dict(r)
                for r in db.execute(
                    f"""
                    SELECT jc.name AS job_category, SUM(jcs.score) AS total_score
                    FROM job_category_scores jcs
                    JOIN job_categories jc ON jc.id = jcs.job_category_id
                    JOIN question_options qo ON qo.id = jcs.option_id
                    WHERE qo.code IN ({placeholders})
                    GROUP BY jc.name
                    ORDER BY total_score DESC
                    """,
                    detected_codes,
                ).fetchall()
            ]

        result = llm.recommend(conversation, job_categories, candidate_jobs, rule_scores)

        items = []
        for rank, rec in enumerate(result["recommendations"], start=1):
            job_row = db.execute(
                "SELECT avg_salary_band, outlook FROM koeco_jobs WHERE name = ?",
                (rec.get("koeco_job_name") or "",),
            ).fetchone()
            items.append(
                RecommendationItem(
                    rank=rank,
                    job_category=rec["job_category"],
                    koeco_job_name=rec.get("koeco_job_name") or None,
                    avg_salary_band=job_row["avg_salary_band"] if job_row else None,
                    outlook=job_row["outlook"] if job_row else None,
                    reason_text=rec["reason_text"],
                )
            )

            job_category_row = db.execute(
                "SELECT id FROM job_categories WHERE name = ?", (rec["job_category"],)
            ).fetchone()
            koeco_job_row = db.execute(
                "SELECT id FROM koeco_jobs WHERE name = ?", (rec.get("koeco_job_name") or "",)
            ).fetchone()
            if job_category_row:
                db.execute(
                    "INSERT INTO job_recommendations "
                    "(session_id, job_category_id, koeco_job_id, rank, reason_text) VALUES (?, ?, ?, ?, ?)",
                    (
                        session_id,
                        job_category_row["id"],
                        koeco_job_row["id"] if koeco_job_row else None,
                        rank,
                        rec["reason_text"],
                    ),
                )

        db.execute(
            "UPDATE sessions SET status = '완료', counselor_summary = ? WHERE id = ?",
            (result["counselor_summary"], session_id),
        )

    return RecommendResponse(
        session_id=session_id,
        recommendations=items,
        counselor_summary=result["counselor_summary"],
    )


# --- 프론트 연결용 직무 조회 API ---

# 461개 공식 직업(koeco_official_jobs) 기준.
# 일부 직업은 wagework.go.kr에서 수집한 연봉/전망/설명(koeco_jobs)이 이름으로 매칭되어 함께 반환된다.
_JOBS_SQL = """
    SELECT
        j.id            AS id,
        j.code          AS code,
        j.name          AS name,
        c.id            AS categoryId,
        c.name          AS categoryName,
        k.avg_salary_band AS avgSalaryBand,
        k.outlook       AS outlook,
        k.description   AS description
    FROM koeco_official_jobs j
    JOIN koeco_categories c ON c.id = j.major_category_id
    LEFT JOIN koeco_jobs k ON k.name = j.name
"""


@app.get("/api/jobs", response_model=JobListResponse)
def list_jobs(
    categoryIds: Optional[str] = Query(
        None, description="쉼표로 구분한 대분류 id 목록 (예: 1,2). 생략하면 전체 반환"
    )
):
    where = ""
    params: List = []
    if categoryIds:
        try:
            ids = [int(x) for x in categoryIds.split(",") if x.strip()]
        except ValueError:
            raise HTTPException(400, "categoryIds는 쉼표로 구분한 정수여야 합니다. 예: categoryIds=1,2")
        if ids:
            where = " WHERE c.id IN (%s)" % ",".join("?" for _ in ids)
            params = ids

    with get_db() as db:
        rows = db.execute(_JOBS_SQL + where + " ORDER BY j.code", params).fetchall()

    items = [JobItem(**dict(r)) for r in rows]
    return JobListResponse(total=len(items), items=items)


@app.get("/api/categories", response_model=CategoryListResponse)
def list_categories():
    """프론트에서 categoryIds 필터에 쓸 대분류 목록."""
    with get_db() as db:
        rows = db.execute(
            """
            SELECT c.id AS id, c.name AS name, COUNT(j.id) AS jobCount
            FROM koeco_categories c
            LEFT JOIN koeco_official_jobs j ON j.major_category_id = c.id
            GROUP BY c.id, c.name
            ORDER BY c.id
            """
        ).fetchall()

    items = [CategoryItem(**dict(r)) for r in rows]
    return CategoryListResponse(total=len(items), items=items)


@app.get("/api/health")
@app.get("/health")
def health():
    """프론트는 /api/health를 쓰면 되고, /health도 그대로 동작한다."""
    return {"status": "ok"}
