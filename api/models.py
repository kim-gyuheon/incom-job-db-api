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


# --- 음성 상담 (POST /api/sessions, .../voice-answers, .../voice-recommendations) ---
# 프론트 v4 계약과 필드명을 1:1로 맞춘다(전부 camelCase).


class SessionCreateRequest(BaseModel):
    deviceHash: Optional[str] = None   # 키오스크 단말 구분용(선택)


class SessionCreateResponse(BaseModel):
    sessionId: str
    createdAt: str                     # ISO 8601 UTC
    expiresAt: str                     # createdAt + maxTtlSeconds
    idleTimeoutSeconds: int            # 이 시간 동안 요청이 없으면 세션 만료
    maxTtlSeconds: int                 # 활동이 있어도 이 시간이 지나면 만료


class AudioPayload(BaseModel):
    format: str                        # webm / ogg / mp4 / m4a / mp3 / wav
    codec: Optional[str] = None        # opus 등
    encoding: str = "base64"
    sampleRate: Optional[int] = None
    durationMs: Optional[int] = None
    data: str                          # base64로 인코딩한 오디오 본문


class VoiceAnswerRequest(BaseModel):
    questionKey: str                   # B / D / E / F (questions.step)
    audio: AudioPayload


class VoiceAnswerResponse(BaseModel):
    sessionId: str
    questionKey: str
    status: str                        # ok | no_speech
    sttText: str
    keywords: List[str]                # 매칭된 tags.code 목록
    confidence: Optional[float]
    answeredAt: str


class RecommendedJob(JobItem):
    """/api/jobs와 동일한 직무 구조 + 추천 사유."""

    reason: str
    matchedKeywords: List[str]


class VoiceRecommendationResponse(BaseModel):
    sessionId: str
    basedOnQuestions: List[str]        # 이 추천에 실제로 쓰인 questionKey 목록
    generatedAt: str
    total: int
    isFallback: bool                   # 태그 매칭 실패로 기본 추천을 낸 경우 true
    jobs: List[RecommendedJob]


class ApiErrorDetail(BaseModel):
    errorCode: str
    message: str
    questionKey: Optional[str] = None
    missing: Optional[List[str]] = None


class ApiErrorResponse(BaseModel):
    """오류 응답은 항상 {"detail": {errorCode, message, questionKey, missing}} 형태."""

    detail: ApiErrorDetail
