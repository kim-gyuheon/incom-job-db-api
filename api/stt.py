"""음성 -> 텍스트 변환 계층.

Claude(Anthropic) API는 오디오 입력을 받지 않으므로 STT는 별도 공급자가 필요하다.
공급자는 STT_PROVIDER 환경변수로 고른다.

  STT_PROVIDER=openai   OPENAI_API_KEY 로 Whisper 전사 API 호출 (실제 음성 인식)
  STT_PROVIDER=mock     고정 문장을 돌려준다. 프론트 통합 테스트용으로,
                        마이크/과금 없이 세 엔드포인트 전체 흐름을 확인할 수 있다.
  (미설정)              STT_UNAVAILABLE 오류. 조용히 가짜 결과를 주지 않는다.

새 공급자를 붙일 때는 transcribe()에 분기만 추가하면 된다.
"""

import math
import os
from typing import Dict, Optional

import httpx

# 프론트가 MediaRecorder로 보내는 조합만 우선 허용한다.
SUPPORTED_FORMATS = {"webm", "ogg", "mp4", "m4a", "mp3", "wav"}
MAX_AUDIO_BYTES = 10 * 1024 * 1024
MAX_DURATION_MS = 60_000

_OPENAI_URL = "https://api.openai.com/v1/audio/transcriptions"
_OPENAI_MODEL = os.environ.get("STT_MODEL", "whisper-1")

# mock 공급자가 questionKey별로 돌려주는 문장. 실제 태그가 잡히도록 태그 설명과
# 결이 맞는 표현을 골랐다.
_MOCK_TEXT = {
    "C": "오래 서 있는 건 힘들고 밤에 일하는 것도 어려워요.",
    "D": "예전에 사무실에서 서류 정리하고 자료 입력하는 일을 오래 했어요.",
    "E": "앞으로도 사무실에서 서류 다루는 일을 하고 싶어요.",
    "F": "컴퓨터로 입력하는 건 자신 있고 사람 만나서 이야기하는 것도 괜찮아요.",
    "G": "자격증은 따로 없어요.",
}


class SttError(RuntimeError):
    """STT 단계에서 실패했음을 알린다. error_code는 그대로 응답에 실린다."""

    def __init__(self, error_code: str, message: str, status_code: int = 502):
        super().__init__(message)
        self.error_code = error_code
        self.message = message
        self.status_code = status_code


def provider() -> Optional[str]:
    """현재 설정된 공급자 이름. 설정이 없거나 자격 증명이 없으면 None."""
    name = (os.environ.get("STT_PROVIDER") or "").strip().lower()
    if name == "openai" and not os.environ.get("OPENAI_API_KEY"):
        return None
    return name or None


def transcribe(audio_bytes: bytes, audio_format: str, question_key: str) -> Dict:
    """{"text": str, "confidence": Optional[float]} 를 돌려준다."""
    name = provider()
    if name is None:
        raise SttError(
            "STT_UNAVAILABLE",
            "음성 인식 공급자가 설정되지 않았습니다. STT_PROVIDER 환경변수를 "
            "'openai'(+OPENAI_API_KEY) 또는 통합 테스트용 'mock'으로 설정하세요.",
            status_code=503,
        )
    if name == "mock":
        return {"text": _MOCK_TEXT.get(question_key, _MOCK_TEXT["D"]), "confidence": 0.99}
    if name == "openai":
        return _transcribe_openai(audio_bytes, audio_format)
    raise SttError(
        "STT_UNAVAILABLE",
        "알 수 없는 STT_PROVIDER 값입니다: %s" % name,
        status_code=503,
    )


def _transcribe_openai(audio_bytes: bytes, audio_format: str) -> Dict:
    files = {"file": ("audio.%s" % audio_format, audio_bytes, "audio/%s" % audio_format)}
    data = {"model": _OPENAI_MODEL, "language": "ko", "response_format": "verbose_json"}
    try:
        response = httpx.post(
            _OPENAI_URL,
            headers={"Authorization": "Bearer %s" % os.environ["OPENAI_API_KEY"]},
            files=files,
            data=data,
            timeout=60.0,
        )
    except httpx.HTTPError as exc:
        raise SttError("STT_FAILED", "음성 인식 서버에 연결하지 못했습니다: %s" % exc)

    if response.status_code >= 400:
        raise SttError(
            "STT_FAILED",
            "음성 인식에 실패했습니다 (HTTP %d)." % response.status_code,
        )

    payload = response.json()
    return {
        "text": (payload.get("text") or "").strip(),
        "confidence": _confidence_from_segments(payload.get("segments") or []),
    }


def _confidence_from_segments(segments) -> Optional[float]:
    """Whisper는 신뢰도를 직접 주지 않으므로 세그먼트 평균 logprob에서 환산한다."""
    logprobs = [s["avg_logprob"] for s in segments if s.get("avg_logprob") is not None]
    if not logprobs:
        return None
    return round(math.exp(sum(logprobs) / len(logprobs)), 4)
