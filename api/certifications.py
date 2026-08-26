"""자격증 카탈로그 조회 엔드포인트.

  GET /api/certifications              목록·검색
  GET /api/certifications/groups       분야 그룹 목록(화면 필터용)
  GET /api/certifications/{certCode}   상세 + 연결된 직무

읽기 전용이고 기존 음성 상담 흐름(POST /api/sessions ...)에는 영향을 주지 않는다.
자격증으로 추천 점수를 조정하는 것은 job_codes 사람 검수(verified) 이후에 별도로 다룬다.
"""

from typing import Optional

from fastapi import APIRouter, Path, Query

import cert_db
from models import (
    ApiErrorResponse,
    CertificationDetail,
    CertificationGroupList,
    CertificationListResponse,
)
from voice import api_error

router = APIRouter(prefix="/api", tags=["자격증"])


@router.get(
    "/certifications",
    response_model=CertificationListResponse,
    summary="자격증 목록 조회",
    description=(
        "Q-net 종목 기준 486종. `query`는 종목명 부분 일치, `fieldGroup`은 화면용 분야"
        " 그룹, `grade`는 기술사·기능장·기사·산업기사·기능사 등 등급으로 거른다."
    ),
)
def list_certifications(
    query: Optional[str] = Query(None, description="종목명 부분 검색"),
    fieldGroup: Optional[str] = Query(None, description="분야 그룹 (예: electric)"),
    grade: Optional[str] = Query(None, description="등급 (예: 기능사)"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    result = cert_db.search_certifications(
        query=query, field_group=fieldGroup, grade=grade, limit=limit, offset=offset
    )
    return CertificationListResponse(**result)


@router.get(
    "/certifications/groups",
    response_model=CertificationGroupList,
    summary="자격증 분야 그룹 목록",
    description="화면 필터에 쓸 그룹 코드와 각 그룹의 종목 수. 연결·검수 현황도 함께 준다.",
)
def list_certification_groups():
    return CertificationGroupList(items=cert_db.field_groups(), **cert_db.link_stats())


@router.get(
    "/certifications/{certCode}",
    response_model=CertificationDetail,
    responses={404: {"model": ApiErrorResponse}},
    summary="자격증 상세 + 연결된 직무",
    description=(
        "`linkedJobs`는 자격증의 KECO 세분류 코드가 가리키는 소분류에 속한 직무들이다."
        " 이름 매칭으로 이어붙인 값이라 비어 있을 수 있고, `verified=false`면 아직 사람"
        " 검수를 거치지 않은 매핑이라는 뜻이다."
    ),
)
def get_certification(certCode: str = Path(..., description="종목코드")):
    item = cert_db.get_certification(certCode)
    if item is None:
        raise api_error(
            404, "CERTIFICATION_NOT_FOUND", "해당 종목코드의 자격증이 없습니다."
        )
    return CertificationDetail(**item)
