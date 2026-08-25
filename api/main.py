from contextlib import asynccontextmanager
from typing import List, Optional

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse

from db import JOBS_SQL, get_db
from models import (
    CategoryItem,
    CategoryListResponse,
    JobItem,
    JobListResponse,
)
from voice import router as voice_router
from voice_db import ensure_voice_schema


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Render 무료 플랜은 배포마다 job.db가 새로 펼쳐지므로 매 부팅 때 스키마를 보정한다."""
    ensure_voice_schema()
    yield


app = FastAPI(title="희망직종 길잡이 API", lifespan=lifespan)

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


# 음성 상담 엔드포인트 3개 (POST /api/sessions, .../voice-answers, .../voice-recommendations)
app.include_router(voice_router)


def custom_openapi():
    """FastAPI가 자동으로 넣는 422를 스펙에서 뺀다.

    요청 검증 실패는 위 핸들러가 400 VALIDATION_ERROR로 바꿔 내보내므로,
    422가 남아 있으면 프론트가 없는 응답을 처리하게 된다.
    """
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(
        title=app.title,
        version=app.version,
        routes=app.routes,
    )
    for path in schema.get("paths", {}).values():
        for operation in path.values():
            responses = operation.get("responses", {})
            if responses.pop("422", None) is None:
                continue
            responses.setdefault(
                "400",
                {
                    "description": "요청 오류",
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/ApiErrorResponse"}
                        }
                    },
                },
            )
    app.openapi_schema = schema
    return schema


app.openapi = custom_openapi


@app.exception_handler(RequestValidationError)
def _validation_error_handler(request: Request, exc: RequestValidationError):
    """요청 본문 검증 실패도 계약과 같은 detail 형태로 내보낸다."""
    first = exc.errors()[0] if exc.errors() else {}
    location = ".".join(str(part) for part in first.get("loc", ())[1:])
    return JSONResponse(
        status_code=400,
        content={
            "detail": {
                "errorCode": "VALIDATION_ERROR",
                "message": "요청 형식이 올바르지 않습니다: %s (%s)"
                % (location or "body", first.get("msg", "검증 실패")),
                "questionKey": None,
                "missing": None,
            }
        },
    )


@app.exception_handler(HTTPException)
def _http_exception_handler(request: Request, exc: HTTPException):
    """detail이 문자열인 기본 오류(404 등)도 같은 형태로 감싼다."""
    if isinstance(exc.detail, dict):
        detail = exc.detail
    else:
        detail = {
            "errorCode": "HTTP_%d" % exc.status_code,
            "message": str(exc.detail),
            "questionKey": None,
            "missing": None,
        }
    return JSONResponse(status_code=exc.status_code, content={"detail": detail},
                        headers=getattr(exc, "headers", None))


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
        rows = db.execute(JOBS_SQL + where + " ORDER BY c1.id, j.id", params).fetchall()

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
            "POST /api/sessions": "음성 상담 세션 생성",
            "POST /api/sessions/{sessionId}/voice-answers": "음성 답변 업로드(STT)",
            "POST /api/sessions/{sessionId}/voice-recommendations": "음성 답변 기반 직무 추천",
        },
    }


@app.get("/api/health")
@app.get("/health")
def health():
    """프론트는 /api/health를 쓰면 되고, /health도 그대로 동작한다."""
    return {"status": "ok"}
