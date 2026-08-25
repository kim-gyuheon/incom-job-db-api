"""음성 답변 텍스트에서 태그를 뽑고 추천 이유 문장을 만드는 계층.

ANTHROPIC_API_KEY가 있으면 Claude로 처리하고, 없으면 규칙 기반으로 떨어진다.
Render에 키가 없어도 세 엔드포인트가 500 없이 동작해야 하므로 폴백은 필수다.

기존 llm.py는 conversation_schema.sql(question_options.code, koeco_jobs,
job_category_scores)을 전제로 쓰여 있어 실제 job.db 스키마와 맞지 않는다.
그래서 재사용하지 않고 여기서 job.db의 tags 구조에 맞게 새로 호출한다.

2026-08-26: extract_tag_codes()는 이제 G(자격증)에서만 쓰인다 — C/D/E/F는
voice_engine.extract_positive_and_barrier()(KNOW 82축 엔진의 규칙 기반 정규식 추출기)로
옮겨갔다. build_reasons()는 여전히 다섯 질문 전부의 추천 이유를 쓴다.
"""

import json
import os
from typing import Dict, List, Optional

MODEL = "claude-sonnet-5"

# 규칙 기반 폴백용 표현 사전. tags.code -> 발화에 나올 만한 표현들.
#
# 2026-08-26: C/D/E/F(하기 어려운 일/해본 일/하고 싶은 일/자신 있는 일)는 이제
# voice_engine.extract_positive_and_barrier()(api/tagging.py, 규칙 기반 정규식)가
# 처리해서 이 사전을 안 거친다 — 그래서 EXP_*/CAN_*/HARD_* 항목은 지웠다(voice.py가
# 이 함수를 호출할 때 candidate tags로 CERT만 넘기므로 원래도 죽은 코드였지만, 남겨두면
# "지금 뭘로 답변을 해석하는지" 헷갈려서 정리함). G(자격증)만 여전히 이 방식을 쓴다.
_TAG_SYNONYMS = {
    # '있음'은 "있/땄/취득" 같은 확정 표현만 잡아서
    # "운전면허는 없어요" 같은 문장이 '있음'으로 잡히지 않게 한다.
    "CERT_있음": [
        "자격증이 있", "자격증 있", "면허가 있", "면허 있",
        "자격증을 땄", "면허를 땄", "취득했", "보유하고 있", "가지고 있",
    ],
    "CERT_없음": ["없어요", "없습니다", "없는데", "없고", "모르겠", "안 땄", "하나도 없", "따로 없"],
}


def _client():
    """anthropic 클라이언트. 키가 없으면 None."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return None
    try:
        import anthropic
    except ImportError:
        return None
    return anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])


# --- 태그 추출 -------------------------------------------------------------

_EXTRACT_TOOL = {
    "name": "extract_tags",
    "description": "구직자의 답변에서 해당하는 태그 코드를 골라낸다.",
    "input_schema": {
        "type": "object",
        "properties": {
            "tag_codes": {
                "type": "array",
                "items": {"type": "string"},
                "description": "제공된 태그 목록의 code 중 답변에 해당하는 것만. 없으면 빈 배열.",
            }
        },
        "required": ["tag_codes"],
    },
}

_EXTRACT_SYSTEM = """\
너는 '희망직종 길잡이' 키오스크의 답변 해석기다.
50~60대 이상 구직자가 말로 한 답변을 듣고, 주어진 태그 목록 중 해당하는 것만 고른다.

규칙:
- 반드시 제공된 태그 목록의 code만 쓴다. 목록에 없는 코드를 만들지 않는다.
- 답변에 근거가 분명한 것만 고른다. 추측으로 넓게 고르지 않는다.
- 해당하는 것이 없으면 빈 배열을 반환한다.
"""


def extract_tag_codes(stt_text: str, tags: List[Dict]) -> List[str]:
    """답변 텍스트에서 태그 code 목록을 뽑는다. tags는 후보 태그(같은 category)."""
    if not stt_text.strip() or not tags:
        return []

    client = _client()
    if client is not None:
        try:
            response = client.messages.create(
                model=MODEL,
                max_tokens=512,
                system=_EXTRACT_SYSTEM,
                tools=[_EXTRACT_TOOL],
                tool_choice={"type": "tool", "name": _EXTRACT_TOOL["name"]},
                messages=[
                    {
                        "role": "user",
                        "content": json.dumps(
                            {
                                "candidate_tags": [
                                    {
                                        "code": t["code"],
                                        "label": t["label"],
                                        "description": t.get("description"),
                                    }
                                    for t in tags
                                ],
                                "user_answer": stt_text,
                            },
                            ensure_ascii=False,
                        ),
                    }
                ],
            )
            for block in response.content:
                if block.type == "tool_use":
                    allowed = {t["code"] for t in tags}
                    codes = [c for c in block.input.get("tag_codes", []) if c in allowed]
                    return _dedupe(codes)
        except Exception:
            # LLM이 실패해도 답변을 버리지 않는다. 규칙 기반으로 계속 진행한다.
            pass

    return match_tag_codes_by_keyword(stt_text, tags)


def match_tag_codes_by_keyword(stt_text: str, tags: List[Dict]) -> List[str]:
    """표현 사전으로 태그를 찾는 폴백. ANTHROPIC_API_KEY가 없을 때 쓰인다."""
    text = stt_text.replace(" ", "")
    matched = []
    for tag in tags:
        for word in _TAG_SYNONYMS.get(tag["code"], []):
            if word.replace(" ", "") in text:
                matched.append(tag["code"])
                break
    return _dedupe(matched)


def _dedupe(items: List[str]) -> List[str]:
    seen = set()
    out = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


# --- 추천 이유 -------------------------------------------------------------

_REASON_TOOL = {
    "name": "write_reasons",
    "description": "각 추천 직업에 대해 구직자의 답변에 근거한 추천 이유를 쓴다.",
    "input_schema": {
        "type": "object",
        "properties": {
            "reasons": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "jobId": {"type": "integer", "description": "제공된 직업의 id"},
                        "reason": {
                            "type": "string",
                            "description": "왜 이 직업을 추천하는지 1~2문장, 쉬운 존댓말",
                        },
                    },
                    "required": ["jobId", "reason"],
                },
            }
        },
        "required": ["reasons"],
    },
}

_REASON_SYSTEM = """\
너는 '희망직종 길잡이' 키오스크의 직무 추천 설명자다.
대상은 50~60대 이상 구직자다.

규칙:
- 제공된 직업만 설명한다. 새 직업을 만들지 않는다.
- 구직자가 말한 내용(경험/가능한 일/힘든 일) 중 어떤 부분 때문에 이 일을 골랐는지 짚어준다.
- 전문 용어 없이 쉬운 존댓말로 1~2문장으로 쓴다.
- 확정된 일자리인 것처럼 말하지 않는다. 상담 전 참고용 추천이다.
"""


def build_reasons(jobs: List[Dict], answers: Dict[str, Dict], tag_labels: Dict[str, str]) -> Dict[int, str]:
    """jobId -> 추천 이유. 실패하면 규칙 기반 문장으로 채운다."""
    fallback = {job["id"]: _fallback_reason(job, tag_labels) for job in jobs}

    client = _client()
    if client is None or not jobs:
        return fallback

    payload = {
        "user_answers": [
            {
                "questionKey": key,
                "spokenText": answer["stt_text"],
                "matchedLabels": [tag_labels.get(c, c) for c in answer["keywords"]],
            }
            for key, answer in answers.items()
        ],
        "jobs": [
            {
                "id": job["id"],
                "name": job["name"],
                "easyName": job.get("easyName"),
                "description": job.get("description"),
                "matchedLabels": [tag_labels.get(c, c) for c in job.get("matchedKeywords", [])],
            }
            for job in jobs
        ],
    }
    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=1024,
            system=_REASON_SYSTEM,
            tools=[_REASON_TOOL],
            tool_choice={"type": "tool", "name": _REASON_TOOL["name"]},
            messages=[{"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
        )
        for block in response.content:
            if block.type == "tool_use":
                reasons = dict(fallback)
                for item in block.input.get("reasons", []):
                    if item.get("jobId") in reasons and item.get("reason"):
                        reasons[item["jobId"]] = item["reason"].strip()
                return reasons
    except Exception:
        pass
    return fallback


def _fallback_reason(job: Dict, tag_labels: Dict[str, str]) -> str:
    labels = [tag_labels.get(c, c) for c in job.get("matchedKeywords", [])]
    name = job.get("easyName") or job["name"]
    if not labels:
        return "상담 전 참고용으로 '%s' 일을 함께 살펴보시면 좋겠습니다." % name
    joined = ", ".join("'%s'" % label for label in labels[:3])
    return "말씀해주신 %s 부분이 '%s' 일과 맞아서 골랐습니다." % (joined, name)
