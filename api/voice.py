"""음성 상담 엔드포인트 3개.

  POST /api/sessions
  POST /api/sessions/{sessionId}/voice-answers
  POST /api/sessions/{sessionId}/voice-recommendations

프론트 v4 계약을 기준으로 하며, 오류는 모두
{"detail": {"errorCode": ..., "message": ..., "questionKey": ..., "missing": ...}} 형태다.
"""

import base64
import binascii
from typing import Dict, List, Optional

from fastapi import APIRouter, HTTPException, Path

import stt
import voice_db as store
import voice_llm
from models import (
    ApiErrorResponse,
    SessionCreateRequest,
    SessionCreateResponse,
    VoiceAnswerRequest,
    VoiceAnswerResponse,
    VoiceRecommendationResponse,
)

router = APIRouter(prefix="/api", tags=["음성 상담"])

# 프론트 UX: 추천 5개를 보여주고 사용자가 최대 3개 선택
RECOMMENDATION_LIMIT = 5

_ERRORS = {
    400: {"model": ApiErrorResponse},
    404: {"model": ApiErrorResponse},
    410: {"model": ApiErrorResponse},
}

# 오류 응답은 항상 아래 형태다.
#   {"detail": {"errorCode": ..., "message": ..., "questionKey": ..., "missing": ...}}
_ERROR_CODES_DOC = """
**오류 코드 목록** (응답 본문은 항상
`{"detail": {"errorCode", "message", "questionKey", "missing"}}` 형태)

| HTTP | errorCode | 언제 |
| --- | --- | --- |
| 400 | `VALIDATION_ERROR` | 요청 본문 형식이 맞지 않음 (필수 필드 누락 등) |
| 400 | `INVALID_QUESTION_KEY` | `questionKey`가 C / D / E / F / G 가 아님 |
| 400 | `INVALID_AUDIO` | `audio.data`가 base64로 해석되지 않거나 비어 있음 |
| 400 | `UNSUPPORTED_AUDIO_ENCODING` | `audio.encoding`이 `base64`가 아님 |
| 400 | `MISSING_ANSWERS` | 추천에 필요한 답변 부족. `missing`에 남은 questionKey |
| 404 | `SESSION_NOT_FOUND` | 세션 id가 없음 |
| 410 | `SESSION_EXPIRED` | 유휴 120초 또는 최대 1200초 초과 |
| 413 | `AUDIO_TOO_LONG` | 녹음 길이가 60초 초과 |
| 413 | `AUDIO_TOO_LARGE` | 오디오 용량이 10MB 초과 |
| 415 | `UNSUPPORTED_AUDIO_FORMAT` | webm / ogg / mp4 / m4a / mp3 / wav 외 |
| 502 | `STT_FAILED` | 음성 인식 서버 호출 실패 |
| 503 | `STT_UNAVAILABLE` | STT 공급자 미설정(`STT_PROVIDER`) |
"""


def api_error(
    status_code: int,
    error_code: str,
    message: str,
    question_key: Optional[str] = None,
    missing: Optional[List[str]] = None,
) -> HTTPException:
    """계약에서 정한 오류 본문을 그대로 만들어 준다(네 키를 항상 포함)."""
    return HTTPException(
        status_code=status_code,
        detail={
            "errorCode": error_code,
            "message": message,
            "questionKey": question_key,
            "missing": missing,
        },
    )


def _load_live_session(session_id: str, question_key: Optional[str] = None) -> Dict:
    """세션을 가져오되 없거나 만료됐으면 계약대로 오류를 던진다."""
    session = store.get_session(session_id)
    if session is None:
        raise api_error(
            404,
            "SESSION_NOT_FOUND",
            "세션을 찾을 수 없습니다. 처음부터 다시 시작해주세요.",
            question_key,
        )
    if store.is_expired(session):
        raise api_error(
            410,
            "SESSION_EXPIRED",
            "세션이 만료되었습니다. 처음부터 다시 시작해주세요.",
            question_key,
        )
    return session


# --- POST /api/sessions ----------------------------------------------------


@router.post(
    "/sessions",
    response_model=SessionCreateResponse,
    status_code=201,
    summary="상담 세션 생성",
)
def create_session(body: Optional[SessionCreateRequest] = None):
    """키오스크 방문 1회 = 세션 1개. 이후 두 엔드포인트는 이 sessionId를 쓴다."""
    created = store.create_session(body.deviceHash if body else None)
    return SessionCreateResponse(
        sessionId=created["id"],
        createdAt=store.to_iso(created["started_at"]),
        expiresAt=store.to_iso(created["expires_at"]),
        idleTimeoutSeconds=store.IDLE_TIMEOUT_SECONDS,
        maxTtlSeconds=store.MAX_TTL_SECONDS,
    )


# --- POST /api/sessions/{sessionId}/voice-answers --------------------------


def _decode_audio(audio, question_key: str) -> bytes:
    if (audio.encoding or "").lower() != "base64":
        raise api_error(
            400,
            "UNSUPPORTED_AUDIO_ENCODING",
            "audio.encoding은 base64만 지원합니다.",
            question_key,
        )

    audio_format = (audio.format or "").lower()
    if audio_format not in stt.SUPPORTED_FORMATS:
        raise api_error(
            415,
            "UNSUPPORTED_AUDIO_FORMAT",
            "지원하지 않는 오디오 형식입니다: %s (지원: %s)"
            % (audio.format, ", ".join(sorted(stt.SUPPORTED_FORMATS))),
            question_key,
        )

    if audio.durationMs is not None and audio.durationMs > stt.MAX_DURATION_MS:
        raise api_error(
            413,
            "AUDIO_TOO_LONG",
            "녹음이 너무 깁니다. %d초 이내로 다시 말씀해주세요."
            % (stt.MAX_DURATION_MS // 1000),
            question_key,
        )

    try:
        raw = base64.b64decode(audio.data, validate=True)
    except (binascii.Error, ValueError):
        raise api_error(400, "INVALID_AUDIO", "audio.data를 base64로 해석할 수 없습니다.", question_key)

    if not raw:
        raise api_error(400, "INVALID_AUDIO", "오디오 데이터가 비어 있습니다.", question_key)
    if len(raw) > stt.MAX_AUDIO_BYTES:
        raise api_error(
            413,
            "AUDIO_TOO_LARGE",
            "오디오 용량이 너무 큽니다. %dMB 이내로 보내주세요."
            % (stt.MAX_AUDIO_BYTES // (1024 * 1024)),
            question_key,
        )
    return raw


@router.post(
    "/sessions/{sessionId}/voice-answers",
    response_model=VoiceAnswerResponse,
    responses=_ERRORS,
    summary="음성 답변 업로드 (STT + 키워드 추출)",
    description="오디오를 전사해 태그(keywords)를 뽑아 저장한다. "
    "말이 잡히지 않으면 오류가 아니라 `status: \"no_speech\"`로 200을 돌려준다."
    + _ERROR_CODES_DOC,
)
def submit_voice_answer(
    body: VoiceAnswerRequest,
    sessionId: str = Path(..., description="POST /api/sessions로 받은 세션 id"),
):
    question_key = (body.questionKey or "").strip().upper()
    _load_live_session(sessionId, question_key)

    question = store.voice_question(question_key)
    if question is None:
        raise api_error(
            400,
            "INVALID_QUESTION_KEY",
            "questionKey는 %s 중 하나여야 합니다." % ", ".join(store.QUESTION_KEYS),
            question_key or None,
        )

    audio_bytes = _decode_audio(body.audio, question_key)

    try:
        result = stt.transcribe(audio_bytes, (body.audio.format or "").lower(), question_key)
    except stt.SttError as exc:
        raise api_error(exc.status_code, exc.error_code, exc.message, question_key)

    stt_text = (result.get("text") or "").strip()
    confidence = result.get("confidence")

    if not stt_text:
        # 말이 잡히지 않은 경우. 오류로 끊지 않고 다시 말하게 한다(저장하지 않음).
        store.touch_session(sessionId)
        return VoiceAnswerResponse(
            sessionId=sessionId,
            questionKey=question_key,
            status="no_speech",
            sttText="",
            keywords=[],
            confidence=confidence,
            answeredAt=store.to_iso(store.utcnow()),
        )

    question_id = question["question_id"]
    keywords = voice_llm.extract_tag_codes(
        stt_text, store.tags_by_category(question["tag_category"])
    )
    matched = set(keywords)
    option_ids = [
        o["id"] for o in store.options_for_question(question_id) if o["tag_code"] in matched
    ]

    answered_at = store.save_voice_answer(
        session_id=sessionId,
        question_key=question_key,
        stt_text=stt_text,
        keywords=keywords,
        confidence=confidence,
        audio_meta={
            "format": body.audio.format,
            "codec": body.audio.codec,
            "sampleRate": body.audio.sampleRate,
            "durationMs": body.audio.durationMs,
        },
        option_ids=option_ids,
        question_id=question_id,
    )
    store.touch_session(sessionId, last_step=question_key)

    return VoiceAnswerResponse(
        sessionId=sessionId,
        questionKey=question_key,
        status="ok",
        sttText=stt_text,
        keywords=keywords,
        confidence=confidence,
        answeredAt=store.to_iso(answered_at),
    )


# --- POST /api/sessions/{sessionId}/voice-recommendations -----------------


def _score_jobs(positive: set, difficult: set, exclude_cert: bool) -> List[Dict]:
    """job_tags로 직업을 채점한다.

    - D(해본 일) / E(하고 싶은 일) / F(자신 있는 일)에서 잡힌 태그가 직업의
      REQUIRED / BONUS 태그와 겹치면 weight만큼 더한다.
    - C(하기 어려운 일)에서 잡힌 태그가 직업의 EXCLUDE_IF_DIFFICULT에 걸리면 제외한다.
    - G(자격증)에서 '없음'이 잡히면 자격증이 필요한 직업을 제외한다.
    """
    cert_required = store.jobs_requiring_cert() if exclude_cert else set()

    by_job: Dict[int, Dict] = {}
    for row in store.recommendable_job_tags():
        entry = by_job.setdefault(
            row["job_id"], {"score": 0, "matched": [], "excluded": False}
        )
        code = row["tag_code"]
        if row["role"] == "EXCLUDE_IF_DIFFICULT":
            if code in difficult:
                entry["excluded"] = True
            continue
        if code in positive:
            entry["score"] += row["weight"]
            if code not in entry["matched"]:
                entry["matched"].append(code)

    scored = [
        {"id": job_id, "score": data["score"], "matchedKeywords": data["matched"]}
        for job_id, data in by_job.items()
        if not data["excluded"] and data["score"] > 0 and job_id not in cert_required
    ]
    # 점수 내림차순, 동점이면 매칭 태그 수 -> id 순으로 안정 정렬
    scored.sort(key=lambda x: (-x["score"], -len(x["matchedKeywords"]), x["id"]))
    return scored


@router.post(
    "/sessions/{sessionId}/voice-recommendations",
    response_model=VoiceRecommendationResponse,
    responses=_ERRORS,
    summary="음성 답변 기반 직무 추천",
    description="저장된 음성 답변의 태그로 직무를 채점해 상위 %d개를 돌려준다."
    % RECOMMENDATION_LIMIT
    + _ERROR_CODES_DOC,
)
def create_voice_recommendations(
    sessionId: str = Path(..., description="POST /api/sessions로 받은 세션 id"),
):
    _load_live_session(sessionId)

    answers = store.active_voice_answers(sessionId)
    missing = [key for key in store.REQUIRED_QUESTION_KEYS if key not in answers]
    if missing:
        raise api_error(
            400,
            "MISSING_ANSWERS",
            "추천에 필요한 답변이 부족합니다. 남은 질문에 먼저 답해주세요.",
            missing=missing,
        )

    # D 해본 일 / E 하고 싶은 일 / F 자신 있는 일 -> 점수를 올리는 신호
    positive = set()
    for key in ("D", "E", "F"):
        if key in answers:
            positive.update(answers[key]["keywords"])
    # C 하기 어려운 일 -> 제외 조건
    difficult = set(answers["C"]["keywords"]) if "C" in answers else set()
    # G 자격증 -> '없음'만 잡혔으면 자격증이 필요한 직업을 뺀다
    cert_keywords = set(answers["G"]["keywords"]) if "G" in answers else set()
    exclude_cert = "CERT_없음" in cert_keywords and "CERT_있음" not in cert_keywords

    scored = _score_jobs(positive, difficult, exclude_cert)
    is_fallback = not scored
    if is_fallback:
        scored = [
            {"id": job_id, "score": 0, "matchedKeywords": []}
            for job_id in store.fallback_job_ids(RECOMMENDATION_LIMIT)
        ]
    scored = scored[:RECOMMENDATION_LIMIT]

    jobs_by_id = store.fetch_jobs([s["id"] for s in scored])
    items = []
    for entry in scored:
        job = jobs_by_id.get(entry["id"])
        if job is None:
            continue
        job = dict(job)
        job["requiresCert"] = bool(job["requiresCert"])
        job["isRecommendable"] = bool(job["isRecommendable"])
        job["matchedKeywords"] = entry["matchedKeywords"]
        job["score"] = entry["score"]
        items.append(job)

    tag_labels = store.all_tag_labels()
    reasons = voice_llm.build_reasons(items, answers, tag_labels)
    for job in items:
        job["reason"] = reasons.get(job["id"], "")

    generated_at = store.save_recommendations(sessionId, items, is_fallback)

    for job in items:
        job.pop("score", None)   # score는 내부 채점값이라 응답에 넣지 않는다

    # 추천에 실제로 쓰인 questionKey. D/E는 필수, F는 답했을 때만 제외 조건으로 반영된다.
    based_on = [key for key in store.QUESTION_KEYS if key in answers]

    return VoiceRecommendationResponse(
        sessionId=sessionId,
        basedOnQuestions=based_on,
        generatedAt=store.to_iso(generated_at),
        total=len(items),
        isFallback=is_fallback,
        jobs=items,
    )
