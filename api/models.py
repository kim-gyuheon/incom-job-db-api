from typing import List, Optional

from pydantic import BaseModel


class SessionStartResponse(BaseModel):
    session_id: int
    turn_no: int
    question_text: str


class AnswerRequest(BaseModel):
    answer: str


class AnswerResponse(BaseModel):
    session_id: int
    turn_no: int
    done: bool
    question_text: Optional[str] = None  # next question, absent when done


class RecommendationItem(BaseModel):
    rank: int
    job_category: str
    koeco_job_name: Optional[str]
    avg_salary_band: Optional[str]
    outlook: Optional[str]
    reason_text: str


class RecommendResponse(BaseModel):
    session_id: int
    recommendations: List[RecommendationItem]
    counselor_summary: str


# --- GET /api/jobs (프론트 연결용 직무 목록 조회) ---


class JobItem(BaseModel):
    id: int
    code: str                       # 한국고용직업분류(KECO) 2025 세분류 코드
    name: str                       # 직업명
    categoryId: int                 # 대분류 id
    categoryName: str               # 대분류명
    avgSalaryBand: Optional[str]    # 평균연봉 구간 (데이터 있는 직업만)
    outlook: Optional[str]          # 미래전망 (데이터 있는 직업만)
    description: Optional[str]      # 하는 일 (데이터 있는 직업만)


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
