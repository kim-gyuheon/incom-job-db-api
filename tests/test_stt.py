"""stt.py의 공급자 선택/디스패치 검증.

실제 faster-whisper 모델 로딩·전사는 여기서 테스트하지 않는다(모델 다운로드가 필요해서
CI/로컬에서 무겁고 느림) — dispatch 로직과 입력 검증만 확인한다.
"""

from __future__ import annotations

import sys
import threading
import time
import types

import stt


def test_provider_none_when_unset(monkeypatch):
    monkeypatch.delenv("STT_PROVIDER", raising=False)
    assert stt.provider() is None


def test_provider_local_needs_no_api_key(monkeypatch):
    monkeypatch.setenv("STT_PROVIDER", "local")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert stt.provider() == "local"


def test_provider_openai_requires_api_key(monkeypatch):
    monkeypatch.setenv("STT_PROVIDER", "openai")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert stt.provider() is None  # 키 없이는 openai를 쓸 수 없다.

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    assert stt.provider() == "openai"


def test_transcribe_raises_unavailable_when_no_provider(monkeypatch):
    monkeypatch.delenv("STT_PROVIDER", raising=False)
    try:
        stt.transcribe(b"fake-audio", "webm", "D")
        assert False, "STT_UNAVAILABLE을 기대했는데 예외가 안 났다"
    except stt.SttError as exc:
        assert exc.error_code == "STT_UNAVAILABLE"
        assert exc.status_code == 503


def test_transcribe_local_rejects_empty_audio_without_loading_model(monkeypatch):
    """빈 오디오는 모델을 로드하기 전에 걸러져야 한다(불필요한 모델 다운로드 방지)."""
    monkeypatch.setenv("STT_PROVIDER", "local")
    monkeypatch.setattr(stt, "_local_transcriber", None)
    try:
        stt.transcribe(b"", "webm", "D")
        assert False, "INVALID_AUDIO를 기대했는데 예외가 안 났다"
    except stt.SttError as exc:
        assert exc.error_code == "INVALID_AUDIO"
    # 빈 오디오 검증에서 바로 끊겼으니 모델 로딩 시도조차 안 했어야 한다.
    assert stt._local_transcriber is None


def test_mock_provider_returns_question_specific_text(monkeypatch):
    monkeypatch.setenv("STT_PROVIDER", "mock")
    result = stt.transcribe(b"ignored", "webm", "G")
    assert result["text"] == stt._MOCK_TEXT["G"]
    assert result["confidence"] == 0.99


def test_local_transcriber_loads_only_once_under_concurrent_requests(monkeypatch):
    """회귀 테스트: 락 없이 `if _local_transcriber is None: ... 로드 ...`만 있으면, 동시에
    들어온 요청 두 개가 둘 다 None을 보고 WhisperModel을 두 번 로드할 수 있었다(메모리
    두 배 사용 -> Render 무료 플랜에서 OOM 위험). FastAPI가 sync 경로 함수를 스레드풀에서
    돌리므로 이런 동시 호출이 실제로 일어날 수 있다."""
    construct_count = 0
    construct_lock = threading.Lock()

    class FakeInfo:
        language_probability = 1.0

    class FakeWhisperModel:
        def __init__(self, *args, **kwargs):
            nonlocal construct_count
            # 두 스레드가 동시에 "아직 없다"고 판단할 여유를 주기 위해 로딩을 살짝 늦춘다.
            time.sleep(0.05)
            with construct_lock:
                construct_count += 1

        def transcribe(self, path, language="ko"):
            return [], FakeInfo()

    fake_module = types.ModuleType("faster_whisper")
    fake_module.WhisperModel = FakeWhisperModel
    monkeypatch.setitem(sys.modules, "faster_whisper", fake_module)
    monkeypatch.setattr(stt, "_local_transcriber", None)

    errors = []

    def worker():
        try:
            stt._transcribe_local(b"fake-audio-bytes")
        except Exception as exc:  # pragma: no cover - 실패하면 아래 assert가 알려줌
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5)

    assert not errors, f"worker 스레드에서 예외 발생: {errors}"
    assert construct_count == 1, f"WhisperModel이 {construct_count}번 로드됨(1번이어야 함)"


def test_openai_silence_is_filtered_to_no_speech():
    """무음 구간에 Whisper가 만들어낸 문장은 걸러서 no_speech로 넘긴다.

    2026-08-26 배포 서버 실측: 3초 무음 WAV에 "고맙습니다."가 status=ok로 반환됐다.
    프런트 계약상 무음은 예시 문장이 아니라 no_speech여야 한다.
    """
    assert stt._is_silence([{"no_speech_prob": 0.94, "avg_logprob": -0.9}]) is True
    assert stt._is_silence([{"no_speech_prob": 0.71}]) is True


def test_openai_real_speech_is_not_filtered():
    """정상 발화는 무음으로 오판하지 않는다(같은 날 측정한 5문항 수준의 값)."""
    assert stt._is_silence([{"no_speech_prob": 0.02}, {"no_speech_prob": 0.11}]) is False
    assert stt._is_silence([{"no_speech_prob": 0.69}]) is False


def test_openai_missing_segments_treated_as_no_speech():
    """세그먼트가 아예 없으면 전사할 말이 없었다는 뜻이다."""
    assert stt._is_silence([]) is True
    # no_speech_prob 필드를 주지 않는 응답이면 판단 근거가 없으니 텍스트를 살린다.
    assert stt._is_silence([{"avg_logprob": -0.2}]) is False
