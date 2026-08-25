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

# barrier 태그(우리 tag-keyword-dictionary.json)와 barrier-review-combined.csv의
# barrier_id는 원래 같은 어휘라 별도 매핑이 필요 없다(skillmatch-voice-backend와 동일 데이터).


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
        excluded = {
            r["job_id"]
            for r in db.execute(
                "SELECT DISTINCT job_id FROM voice_job_barrier_excludes "
                "WHERE barrier_id IN (%s)" % ",".join("?" for _ in barrier_tag_ids),
                tuple(barrier_tag_ids),
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

    result = engine_recommend(user_vector, kept_ids, kept_vectors, top_k=top_k)

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
