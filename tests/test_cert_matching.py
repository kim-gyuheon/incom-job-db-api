"""cert_matching.py 검증 — STT 텍스트에서 자격증 이름 부분일치 매칭."""

from __future__ import annotations

import cert_matching


def test_matches_known_certification_by_name():
    matches = cert_matching.match_certifications("정보처리기사 자격증 있어요")
    assert matches, "카탈로그에 실제로 있는 자격증인데 하나도 안 잡히면 안 된다"
    assert any(m["name"] == "정보처리기사" for m in matches)


def test_no_certification_mentioned_returns_empty():
    matches = cert_matching.match_certifications("자격증은 따로 없어요")
    assert matches == []


def test_empty_text_returns_empty_without_error():
    assert cert_matching.match_certifications("") == []
    assert cert_matching.match_certifications("   ") == []


def test_limit_caps_the_number_of_matches():
    # 여러 자격증 이름이 한 문장에 다 들어가도 limit을 넘지 않아야 한다.
    text = "정보처리기사 전기기능사 정보처리산업기사 다 있어요"
    matches = cert_matching.match_certifications(text, limit=2)
    assert len(matches) <= 2


def test_no_false_positive_from_very_short_names():
    # 2글자 이하 자격증명은 우연히 문장에 섞여 들어가기 쉬워 매칭 대상에서 제외한다.
    matches = cert_matching.match_certifications("차 없이 대중교통으로 다녀요")
    assert matches == []
