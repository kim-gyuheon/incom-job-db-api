"""stt.py의 공급자 선택/디스패치 검증.

실제 faster-whisper 모델 로딩·전사는 여기서 테스트하지 않는다(모델 다운로드가 필요해서
CI/로컬에서 무겁고 느림) — dispatch 로직과 입력 검증만 확인한다.
"""

from __future__ import annotations

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
