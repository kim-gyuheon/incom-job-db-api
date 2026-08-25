from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import numpy as np

from tagging import TagMatch


ROOT_DIR = Path(__file__).resolve().parents[1]
WEIGHTS_PATH = ROOT_DIR / "reports" / "tag-weight-analysis-82axis.json"


@lru_cache(maxsize=1)
def load_tag_weights() -> dict[str, np.ndarray]:
    data = json.loads(WEIGHTS_PATH.read_text(encoding="utf-8"))
    return {tag: np.array(values, dtype=float) for tag, values in data["tagWeights82"].items()}


def axis_count() -> int:
    weights = load_tag_weights()
    if not weights:
        raise ValueError("tagWeights82 is empty")
    return len(next(iter(weights.values())))


def vectorize_tags(matches: list[TagMatch]) -> np.ndarray:
    # 2026-08-26 QA 수정(Claude Code): 태그 3~4개를 합치면 여러 축이 AXIS_MAX(7.0)로 포화돼서
    # 코사인 유사도가 상대적 크기 정보를 잃고 무관한 직무가 상위로 올라오는 걸 실측으로 확인함
    # (INBUILD 프로토타입 recommendation.js의 동일 수정 참고). 코사인 유사도는 벡터 방향만
    # 보므로 축별 상한 클램프가 애초에 불필요 — 제거함.
    weights = load_tag_weights()
    vector = np.zeros(axis_count(), dtype=float)
    for match in matches:
        if match.category == "barrier":
            continue
        weight = weights.get(match.tag_id)
        if weight is not None:
            vector += weight
    return vector
