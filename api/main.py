from typing import List, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from db import get_db
from models import (
    CategoryItem,
    CategoryListResponse,
    JobItem,
    JobListResponse,
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


# job_categories는 3단계 계층(level 1 대분류 → 2 중분류 → 3 소분류)이고
# jobs.category_id는 항상 level 3을 가리킨다. 따라서 대분류까지 두 번 거슬러 올라간다.
_JOBS_SQL = """
    SELECT
        j.id                AS id,
        j.name              AS name,
        j.easy_name         AS easyName,
        j.one_line_desc     AS description,
        c1.id               AS categoryId,
        c1.name             AS categoryName,
        c2.name             AS subCategoryName,
        c3.name             AS detailCategoryName,
        j.requires_cert     AS requiresCert,
        j.cert_note         AS certNote,
        j.is_recommendable  AS isRecommendable
    FROM jobs j
    JOIN job_categories c3 ON c3.id = j.category_id
    JOIN job_categories c2 ON c2.id = c3.parent_id
    JOIN job_categories c1 ON c1.id = c2.parent_id
"""


@app.get("/api/jobs", response_model=JobListResponse)
def list_jobs(
    categoryIds: Optional[str] = Query(
        None, description="쉼표로 구분한 대분류 id 목록 (예: 1,2). 생략하면 전체 반환"
    ),
    recommendableOnly: bool = Query(
        False, description="true면 추천 대상으로 정리된 직업만 반환"
    ),
):
    conditions: List[str] = []
    params: List = []

    if categoryIds:
        try:
            ids = [int(x) for x in categoryIds.split(",") if x.strip()]
        except ValueError:
            raise HTTPException(400, "categoryIds는 쉼표로 구분한 정수여야 합니다. 예: categoryIds=1,2")
        if ids:
            conditions.append("c1.id IN (%s)" % ",".join("?" for _ in ids))
            params.extend(ids)

    if recommendableOnly:
        conditions.append("j.is_recommendable = 1")

    where = (" WHERE " + " AND ".join(conditions)) if conditions else ""

    with get_db() as db:
        rows = db.execute(_JOBS_SQL + where + " ORDER BY c1.id, j.id", params).fetchall()

    items = [JobItem(**dict(r)) for r in rows]
    return JobListResponse(total=len(items), items=items)


@app.get("/api/categories", response_model=CategoryListResponse)
def list_categories():
    """프론트에서 categoryIds 필터에 쓸 대분류(level 1) 목록."""
    with get_db() as db:
        rows = db.execute(
            """
            SELECT c1.id AS id, c1.name AS name, COUNT(j.id) AS jobCount
            FROM job_categories c1
            LEFT JOIN job_categories c2 ON c2.parent_id = c1.id
            LEFT JOIN job_categories c3 ON c3.parent_id = c2.id
            LEFT JOIN jobs j ON j.category_id = c3.id
            WHERE c1.level = 1
            GROUP BY c1.id, c1.name
            ORDER BY c1.sort_order, c1.id
            """
        ).fetchall()

    items = [CategoryItem(**dict(r)) for r in rows]
    return CategoryListResponse(total=len(items), items=items)


@app.get("/")
def root():
    """루트로 접속했을 때 사용 가능한 엔드포인트를 안내한다."""
    return {
        "service": "희망직종 길잡이 API",
        "docs": "/docs",
        "endpoints": {
            "GET /api/jobs": "직무 목록 전체",
            "GET /api/jobs?recommendableOnly=true": "추천 대상 직무만",
            "GET /api/jobs?categoryIds=1,2": "대분류 id로 필터",
            "GET /api/categories": "대분류 목록",
            "GET /api/health": "상태 확인",
        },
    }


@app.get("/api/health")
@app.get("/health")
def health():
    """프론트는 /api/health를 쓰면 되고, /health도 그대로 동작한다."""
    return {"status": "ok"}
