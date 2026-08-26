"""STT 답변 텍스트에서 실제 자격증 이름을 찾아 매칭한다.

data/cert-catalog.json(국가기술/민간자격 486개, KECO 공식 직업코드로 job_codes까지
연결된 실데이터)을 기준으로, 사용자가 말한 문장 안에 어떤 자격증 이름이 들어있는지
부분일치로 찾는다. G(자격증 보유 여부) 답변처럼 "저 요양보호사 자격증 있어요"류의
문장에서 구체적인 자격증 이름을 뽑아내는 용도 — 기존 CERT_있음/CERT_없음(이분법)과는
별개로, "어떤" 자격증인지까지 프론트엔드에 넘겨주기 위해 추가함.

규칙 기반 부분일치라 LLM/과금 없음. 이름이 겹치는 자격증(예: 등급만 다른 것들)은
문장에서 더 구체적으로(긴 이름 우선) 매칭된 것을 우선한다.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, TypedDict

ROOT_DIR = Path(__file__).resolve().parents[1]
CERT_CATALOG_PATH = ROOT_DIR / "data" / "cert-catalog.json"


class CertMatch(TypedDict):
    code: str
    name: str
    grade: str | None
    kind: str | None


def _normalize(text: str) -> str:
    return re.sub(r"[\s·ㆍ()（）\-]", "", text or "")


@lru_cache(maxsize=1)
def _load_catalog() -> List[Dict]:
    if not CERT_CATALOG_PATH.exists():
        return []
    data = json.loads(CERT_CATALOG_PATH.read_text(encoding="utf-8"))
    # 정규화된 이름을 미리 계산해 둔다(매 요청마다 다시 계산하지 않도록).
    for cert in data:
        cert["_norm_name"] = _normalize(cert.get("name") or "")
    # 이름이 긴 것부터 검사해야 "정보처리기사"가 "정보처리산업기사"에 잘못 걸리는 걸
    # 방지할 수 있다(더 구체적인/긴 이름을 우선 매칭).
    return sorted(data, key=lambda c: len(c["_norm_name"]), reverse=True)


def match_certifications(text: str, limit: int = 3) -> List[CertMatch]:
    """텍스트 안에 이름이 등장하는 자격증을 최대 limit개 찾아 돌려준다.

    짧은 이름(2자 이하)은 오탐(예: "차"가 "택시운전자격" 같은 데 우연히 들어맞는 것)
    위험이 커서 매칭 대상에서 제외한다.
    """
    if not text or not text.strip():
        return []

    normalized_text = _normalize(text)
    matches: List[CertMatch] = []
    seen_codes = set()

    for cert in _load_catalog():
        norm_name = cert["_norm_name"]
        if len(norm_name) <= 2 or not norm_name:
            continue
        if norm_name not in normalized_text:
            continue
        code = cert.get("code")
        if code in seen_codes:
            continue
        seen_codes.add(code)
        matches.append(
            {
                "code": code,
                "name": cert.get("name"),
                "grade": cert.get("grade"),
                "kind": cert.get("kind"),
            }
        )
        if len(matches) >= limit:
            break

    return matches
