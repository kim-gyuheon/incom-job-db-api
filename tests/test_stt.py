"""stt.py의 공급자 선택/디스패치 검증.

2026-08-26: local(faster-whisper) 경로를 완전히 제거하고 openai로 전환했다 —
Render 무료 플랜 메모리 한도와 실사용 인식 품질 사이의 트레이드오프에서 벗어나기
위한 결정. 이제 공급자는 openai/mock 둘뿐이다.
"""

from __future__ import annotations

import stt


def test_provider_none_when_unset(monkeypatch):
    monkeypatch.delenv("STT_PROVIDER", raising=False)
    assert stt.provider() is None


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


def test_transcribe_unknown_provider_value_is_rejected(monkeypatch):
    """local처럼 더 이상 지원하지 않는 값이 들어와도 조용히 넘어가지 않고 에러여야 한다."""
    monkeypatch.setenv("STT_PROVIDER", "local")
    try:
        stt.transcribe(b"fake-audio", "webm", "D")
        assert False, "STT_UNAVAILABLE을 기대했는데 예외가 안 났다"
    except stt.SttError as exc:
        assert exc.error_code == "STT_UNAVAILABLE"


def test_transcribe_openai_rejects_empty_audio(monkeypatch):
    monkeypatch.setenv("STT_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    try:
        stt.transcribe(b"", "webm", "D")
        assert False, "INVALID_AUDIO를 기대했는데 예외가 안 났다"
    except stt.SttError as exc:
        assert exc.error_code == "INVALID_AUDIO"


def test_mock_provider_returns_question_specific_text(monkeypatch):
    monkeypatch.setenv("STT_PROVIDER", "mock")
    result = stt.transcribe(b"ignored", "webm", "G")
    assert result["text"] == stt._MOCK_TEXT["G"]
    assert result["confidence"] == 0.99


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
