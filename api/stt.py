"""음성 -> 텍스트 변환 계층.

Claude(Anthropic) API는 오디오 입력을 받지 않으므로 STT는 별도 공급자가 필요하다.
공급자는 STT_PROVIDER 환경변수로 고른다.

  STT_PROVIDER=openai   OPENAI_API_KEY 로 Whisper 전사 API 호출(요청당 과금).
                        2026-08-26: 원래는 과금을 피하려고 faster-whisper를 같은
                        프로세스에서 직접 돌리는 local 경로가 기본이었는데, Render
                        무료 플랜 메모리 한도와 실사용 인식 품질 사이에서 계속
                        트레이드오프에 시달려서 openai로 완전히 전환하기로 결정함
                        (local 경로/faster-whisper 의존성 자체를 제거했다).
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
            "'openai'(+OPENAI_API_KEY) / 통합 테스트용 'mock' 중 하나로 설정하세요.",
            status_code=503,
        )
    if name == "mock":
        return {"text": _MOCK_TEXT.get(question_key, _MOCK_TEXT["D"]), "confidence": 0.99}
    if name == "openai":
        if not audio_bytes:
            raise SttError("INVALID_AUDIO", "오디오 데이터가 비어 있습니다.", status_code=400)
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
    segments = payload.get("segments") or []
    text = (payload.get("text") or "").strip()
    if _is_silence(segments):
        # 무음이면 빈 문자열로 만들어 호출부가 no_speech로 응답하게 한다.
        text = ""
    return {"text": text, "confidence": _confidence_from_segments(segments)}


# Whisper는 무음 구간에서 상투적인 문장을 만들어내는 경향이 있다(hallucination).
# 2026-08-26 배포 서버 실측: 3초 무음 WAV -> "고맙습니다." 가 status=ok로 반환됨.
# verbose_json의 세그먼트별 no_speech_prob 평균으로 판정한다. 임계값을 0.7로 잡은 건
# 실제 발화(같은 날 측정한 5문항: 2.9~7.3초 한국어)를 잘못 버리지 않도록 보수적으로
# 둔 것 — 무음 hallucination은 보통 0.8을 넘고, 정상 발화는 0.5 아래다.
NO_SPEECH_THRESHOLD = 0.7


def _is_silence(segments) -> bool:
    """세그먼트별 no_speech_prob 평균이 임계값을 넘으면 무음으로 본다."""
    probs = [
        s["no_speech_prob"]
        for s in segments
        if isinstance(s, dict) and s.get("no_speech_prob") is not None
    ]
    if not probs:
        # 세그먼트가 아예 없으면 전사할 말이 없었다는 뜻이다.
        return not segments
    return (sum(probs) / len(probs)) >= NO_SPEECH_THRESHOLD


def _confidence_from_segments(segments) -> Optional[float]:
    """Whisper는 신뢰도를 직접 주지 않으므로 세그먼트 평균 logprob에서 환산한다."""
    logprobs = [s["avg_logprob"] for s in segments if s.get("avg_logprob") is not None]
    if not logprobs:
        return None
    return round(math.exp(sum(logprobs) / len(logprobs)), 4)
