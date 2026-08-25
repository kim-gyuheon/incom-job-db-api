from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
TAG_DICTIONARY_PATH = ROOT_DIR / "reports" / "tag-keyword-dictionary.json"

PARTICLES = ("을", "를", "이", "가", "은", "는", "과", "와", "도", "만", "의", "랑", "이랑")
NEGATIVE_SIGNALS = (
    "원하지 않아",
    "원치 않아",
    "안 원",
    "고 싶지 않",
    "싫",
    "싫어",
    "별로",
    "피하고",
    "힘들",
    "못 하",
    "못하",
    "못 해",
    "못해",
    "어려",
)
SHARED_NEGATION_ANCHOR_RE = re.compile(r"그런\s*(거|게|것)")
SHARED_NEGATION_CONTRAST_RE = re.compile(r"^그런\s*(거|게|것)\s*(말고|아니라|아니고)")
OPPOSITE_BARRIER = {"customer_contact_ok": "customer_contact_avoid"}
NON_BARRIER_CATEGORIES = {"experience", "condition"}


@dataclass(frozen=True)
class TagDefinition:
    category: str
    id: str
    label: str
    keywords: tuple[str, ...]
    patterns: tuple[re.Pattern[str], ...]


@dataclass(frozen=True)
class TagMatch:
    tag_id: str
    category: str
    label: str
    keywords: tuple[str, ...]


def normalize_text(text: str) -> str:
    lowered = text.lower()
    stripped = re.sub(r"[^\w\s가-힣]", " ", lowered)
    return re.sub(r"\s+", " ", stripped).strip()


def build_keyword_regex(keyword: str) -> re.Pattern[str]:
    words = normalize_text(keyword).split()
    if not words:
        return re.compile(r"a^")
    particle = rf"(?:\s*(?:{'|'.join(map(re.escape, PARTICLES))})?\s*)"
    pattern = particle.join(re.escape(word) for word in words)
    return re.compile(pattern, re.IGNORECASE)


@lru_cache(maxsize=1)
def load_tag_definitions() -> tuple[TagDefinition, ...]:
    data = json.loads(TAG_DICTIONARY_PATH.read_text(encoding="utf-8"))
    definitions: list[TagDefinition] = []
    for item in data["tags"]:
        keywords = tuple(item.get("keywords", ()))
        definitions.append(
            TagDefinition(
                category=item["category"],
                id=item["id"],
                label=item["label"],
                keywords=keywords,
                patterns=tuple(build_keyword_regex(keyword) for keyword in keywords),
            )
        )
    return tuple(definitions)


@lru_cache(maxsize=1)
def tag_definition_by_id() -> dict[str, TagDefinition]:
    return {definition.id: definition for definition in load_tag_definitions()}


def has_nearby_negative_signal(text: str, start: int, end: int) -> bool:
    left = max(0, start - 12)
    right = min(len(text), end + 32)
    window = text[left:right]
    return any(signal in window for signal in NEGATIVE_SIGNALS)


def has_shared_list_negation_after(text: str, end: int) -> bool:
    rest = text[end:]
    anchor_match = SHARED_NEGATION_ANCHOR_RE.search(rest)
    if not anchor_match:
        return False
    after_anchor = rest[anchor_match.start() : anchor_match.start() + 20]
    if SHARED_NEGATION_CONTRAST_RE.search(after_anchor):
        return False
    return any(signal in after_anchor for signal in NEGATIVE_SIGNALS)


def _should_skip(definition: TagDefinition, normalized: str, start: int, end: int) -> bool:
    if definition.category in NON_BARRIER_CATEGORIES:
        return has_nearby_negative_signal(normalized, start, end) or has_shared_list_negation_after(normalized, end)
    if definition.id in OPPOSITE_BARRIER:
        return has_nearby_negative_signal(normalized, start, end)
    return False


def extract_tags(text: str) -> list[TagMatch]:
    normalized = normalize_text(text)
    found: dict[str, TagMatch] = {}
    definitions_by_id = tag_definition_by_id()
    for definition in load_tag_definitions():
        matched_keywords: list[str] = []
        for keyword, pattern in zip(definition.keywords, definition.patterns, strict=True):
            match = pattern.search(normalized)
            if not match:
                continue
            if _should_skip(definition, normalized, match.start(), match.end()):
                routed_id = OPPOSITE_BARRIER.get(definition.id)
                if routed_id:
                    routed = definitions_by_id[routed_id]
                    existing = list(found[routed.id].keywords) if routed.id in found else []
                    existing.append(keyword)
                    found[routed.id] = TagMatch(
                        tag_id=routed.id,
                        category=routed.category,
                        label=routed.label,
                        keywords=tuple(dict.fromkeys(existing)),
                    )
                continue
            matched_keywords.append(keyword)
        if matched_keywords:
            found[definition.id] = TagMatch(
                tag_id=definition.id,
                category=definition.category,
                label=definition.label,
                keywords=tuple(dict.fromkeys(matched_keywords)),
            )
    return list(found.values())


def extract_keywords(text: str) -> list[str]:
    keywords: list[str] = []
    for match in extract_tags(text):
        keywords.extend(match.keywords)
    return list(dict.fromkeys(keywords))
