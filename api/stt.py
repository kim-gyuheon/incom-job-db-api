"""음성 -> 텍스트 변환 계층.

Claude(Anthropic) API는 오디오 입력을 받지 않으므로 STT는 별도 공급자가 필요하다.
공급자는 STT_PROVIDER 환경변수로 고른다.

  STT_PROVIDER=local    faster-whisper를 같은 프로세스 안에서 직접 돌린다. 요청당 과금이
                        없다 — 실사용(어르신들이 키오스크에서 계속 말할 때마다) 비용 문제
                        때문에 이쪽을 기본 운영 방식으로 정함(skillmatch-voice-backend와
                        동일 구성). 모델은 첫 요청 때 한 번만 로드된다.
  STT_PROVIDER=openai   OPENAI_API_KEY 로 Whisper 전사 API 호출(요청당 과금). local을 쓸 수
                        없는 환경(예: Render 무료 플랜 메모리 한도)의 대안으로만 남겨둠.
  STT_PROVIDER=mock     고정 문장을 돌려준다. 프론트 통합 테스트용으로,
                        마이크/과금 없이 세 엔드포인트 전체 흐름을 확인할 수 있다.
  (미설정)              STT_UNAVAILABLE 오류. 조용히 가짜 결과를 주지 않는다.

새 공급자를 붙일 때는 transcribe()에 분기만 추가하면 된다.
"""

import math
import os
import tempfile
import threading
from typing import Dict, Optional

import httpx

# 프론트가 MediaRecorder로 보내는 조합만 우선 허용한다.
SUPPORTED_FORMATS = {"webm", "ogg", "mp4", "m4a", "mp3", "wav"}
MAX_AUDIO_BYTES = 10 * 1024 * 1024
MAX_DURATION_MS = 60_000

_OPENAI_URL = "https://api.openai.com/v1/audio/transcriptions"
_OPENAI_MODEL = os.environ.get("STT_MODEL", "whisper-1")

# 2026-08-26: small(int8) 실측 결과 ct2 가중치 파일이 462MB(fp16, 로드 시 int8로
# 양자화되어 절반가량인 ~230MB로 줄지만)라 Render 무료 플랜(512MB) 안에서 FastAPI/
# uvicorn/sqlite 기본 오버헤드까지 더하면 여유가 거의 없다 — 한때 base(139MB, int8
# ~70MB)로 낮췄었는데, 실사용(마이크 음성) 테스트에서 base가 인식을 너무 자주
# 놓쳐서 다시 small로 되돌림. OOM보다 인식 실패가 데모에 더 치명적이라는 판단 —
# Render에서 실제로 메모리 부족이 나면 WHISPER_MODEL_SIZE=base로 대시보드에서
# 바로 되돌릴 수 있다(코드 배포 없이 환경변수만 바꾸면 됨).
_WHISPER_MODEL_SIZE = os.environ.get("WHISPER_MODEL_SIZE", "small")
_WHISPER_DEVICE = os.environ.get("WHISPER_DEVICE", "cpu")
_WHISPER_COMPUTE_TYPE = os.environ.get("WHISPER_COMPUTE_TYPE", "int8")

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
            "'local'(권장, 과금 없음) / 'openai'(+OPENAI_API_KEY) / "
            "통합 테스트용 'mock' 중 하나로 설정하세요.",
            status_code=503,
        )
    if name == "mock":
        return {"text": _MOCK_TEXT.get(question_key, _MOCK_TEXT["D"]), "confidence": 0.99}
    if name == "local":
        return _transcribe_local(audio_bytes)
    if name == "openai":
        return _transcribe_openai(audio_bytes, audio_format)
    raise SttError(
        "STT_UNAVAILABLE",
        "알 수 없는 STT_PROVIDER 값입니다: %s" % name,
        status_code=503,
    )


_local_transcriber = None
# FastAPI는 sync 경로 함수(submit_voice_answer)를 스레드풀에서 돌린다 — 즉 동시에 들어온
# 요청 두 개가 서로 다른 스레드에서 _transcribe_local을 동시에 호출할 수 있다.
# `if _local_transcriber is None: ... 로드 ...`는 확인과 대입 사이에 창이 있어서, 둘 다
# None을 보고 동시에 WhisperModel(...)을 두 번 로드할 수 있다(메모리 두 배로 쓰고, Render
# 무료 플랜 메모리 한도에서 그대로 OOM 위험). 락으로 로딩만 직렬화한다(전사 자체는 잠그지
# 않음 — 여러 키오스크가 붙을 가능성을 생각해 처리량을 불필요하게 죽이지 않기 위해).
_local_transcriber_lock = threading.Lock()


def _transcribe_local(audio_bytes: bytes) -> Dict:
    """faster-whisper로 같은 프로세스 안에서 전사한다. 외부 API 호출이 없어 과금이 없다.

    skillmatch-voice-backend/app/stt.py와 동일 구성(모델 지연 로딩, Windows 임시파일
    PermissionError 회피). 모델은 첫 호출 때만 로드되고 이후 재사용된다.
    """
    global _local_transcriber
    if not audio_bytes:
        raise SttError("INVALID_AUDIO", "오디오 데이터가 비어 있습니다.", status_code=400)
    if _local_transcriber is None:
        with _local_transcriber_lock:
            if _local_transcriber is None:  # 락 기다리는 동안 다른 스레드가 이미 로드했을 수 있음
                try:
                    from faster_whisper import WhisperModel
                except Exception as exc:  # pragma: no cover - dependency boundary
                    raise SttError(
                        "STT_UNAVAILABLE",
                        "faster-whisper를 불러오지 못했습니다: %s" % exc,
                        status_code=503,
                    )
                _local_transcriber = WhisperModel(
                    _WHISPER_MODEL_SIZE, device=_WHISPER_DEVICE, compute_type=_WHISPER_COMPUTE_TYPE
                )

    # NamedTemporaryFile(delete=True)는 파일을 연 채로 유지해서, model.transcribe()가
    # 내부적으로 PyAV/ffmpeg로 같은 경로를 다시 열려고 하면 Windows에서 PermissionError가
    # 난다(skillmatch-voice-backend에서 실측 확인). delete=False로 만들고 쓰기 핸들을 먼저
    # 닫은 뒤 넘기고, finally에서 직접 지운다 — Linux(Render)에서도 그대로 안전하게 동작.
    tmp = tempfile.NamedTemporaryFile(suffix=".webm", delete=False)
    try:
        tmp.write(audio_bytes)
        tmp.flush()
        tmp.close()
        # vad_filter=True: 침묵/노이즈 구간을 먼저 걸러내고 음성이 있는 구간만 전사한다.
        # 꺼져 있으면 마이크 잡음이나 침묵에서 whisper가 없는 말을 지어내는(hallucination)
        # 경우가 늘어나 실제 마이크 입력에서 체감 품질이 떨어진다 — 비용/메모리 영향 없음.
        segments, info = _local_transcriber.transcribe(
            tmp.name, language="ko", vad_filter=True
        )
        segment_list = list(segments)
    except Exception as exc:  # pragma: no cover - dependency boundary
        raise SttError("STT_FAILED", "음성 인식에 실패했습니다: %s" % exc)
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass

    text = " ".join(seg.text.strip() for seg in segment_list if seg.text.strip()).strip()
    no_speech = [getattr(seg, "no_speech_prob", None) for seg in segment_list]
    valid_no_speech = [v for v in no_speech if v is not None]
    avg_no_speech = sum(valid_no_speech) / max(1, len(valid_no_speech))
    language_probability = float(getattr(info, "language_probability", 1.0) or 1.0)
    confidence = max(0.0, min(1.0, language_probability * (1.0 - avg_no_speech)))
    return {"text": text, "confidence": round(confidence, 4)}


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
# local(faster-whisper) 경로는 자체 VAD가 무음이면 세그먼트를 아예 만들지 않아 이 문제가
# 없지만, openai 경로는 전사 텍스트가 그대로 넘어와서 걸러줄 곳이 여기밖에 없다.
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
