from typing import List, Optional

from pydantic import BaseModel

# --- GET /api/jobs (프론트 연결용 직무 목록 조회) ---


class JobItem(BaseModel):
    id: int
    name: str                        # 공식 직업명
    easyName: Optional[str]          # 쉬운 이름 (추천 대상 직업만 채워짐)
    description: Optional[str]       # 한 줄 설명 (추천 대상 직업만 채워짐)
    categoryId: int                  # 대분류(level 1) id
    categoryName: str                # 대분류명
    subCategoryName: Optional[str]   # 중분류(level 2)명
    detailCategoryName: Optional[str]  # 소분류(level 3)명
    requiresCert: bool               # 자격증 필요 여부
    certNote: Optional[str]          # 자격증 관련 안내
    isRecommendable: bool            # 추천 대상 직업인지


class JobListResponse(BaseModel):
    total: int
    items: List[JobItem]


class CategoryItem(BaseModel):
    id: int
    name: str
    jobCount: int


class CategoryListResponse(BaseModel):
    total: int
    items: List[CategoryItem]
