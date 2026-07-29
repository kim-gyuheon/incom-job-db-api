import json
import os
from typing import Dict, List, Optional

import anthropic

MODEL = "claude-sonnet-5"

_client: Optional[anthropic.Anthropic] = None


def client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY 환경변수가 설정되지 않았습니다. .env.example을 참고해 설정하세요."
            )
        _client = anthropic.Anthropic(api_key=api_key)
    return _client


LLM1_TOOL = {
    "name": "llm1_output",
    "description": "사용자 답변에서 감지된 신호와 다음 질문을 반환한다.",
    "input_schema": {
        "type": "object",
        "properties": {
            "detected_option_codes": {
                "type": "array",
                "items": {"type": "string"},
                "description": "이번 사용자 답변에서 감지된 question_options.code 목록 (없으면 빈 배열)",
            },
            "next_question": {
                "type": "string",
                "description": "사용자에게 다음으로 물어볼 자연스럽고 쉬운 질문. ready_to_recommend가 true면 빈 문자열.",
            },
            "ready_to_recommend": {
                "type": "boolean",
                "description": "충분한 정보가 모여 추천 단계로 넘어가도 되는지 여부",
            },
        },
        "required": ["detected_option_codes", "next_question", "ready_to_recommend"],
    },
}

LLM2_TOOL = {
    "name": "llm2_output",
    "description": "대화 내용을 바탕으로 직무 카테고리를 추천한다.",
    "input_schema": {
        "type": "object",
        "properties": {
            "recommendations": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "job_category": {"type": "string", "description": "job_categories.name 중 하나"},
                        "koeco_job_name": {
                            "type": "string",
                            "description": "제공된 실제 직업 목록 중 이 카테고리에 해당하는 구체적 직업명 (없으면 빈 문자열)",
                        },
                        "reason_text": {"type": "string", "description": "사용자 답변에 근거한 추천 이유, 쉬운 말로"},
                    },
                    "required": ["job_category", "reason_text"],
                },
                "minItems": 2,
                "maxItems": 3,
            },
            "counselor_summary": {
                "type": "string",
                "description": "상담원이 참고할 문장형 요약 (화면6)",
            },
        },
        "required": ["recommendations", "counselor_summary"],
    },
}


def _call_tool(system: str, user_content: str, tool: dict) -> dict:
    resp = client().messages.create(
        model=MODEL,
        max_tokens=1024,
        system=system,
        tools=[tool],
        tool_choice={"type": "tool", "name": tool["name"]},
        messages=[{"role": "user", "content": user_content}],
    )
    for block in resp.content:
        if block.type == "tool_use":
            return block.input
    raise RuntimeError("모델이 tool_use 응답을 반환하지 않았습니다.")


LLM1_SYSTEM = """\
너는 '희망직종 길잡이' 키오스크의 대화 진행자(LLM1)다.
대상은 50~60대 이상 구직자이며, 상담 전 몇 가지 쉬운 질문으로 경험/근무조건/관심업무를 파악한다.

규칙:
- 한 번에 하나의 짧고 쉬운 질문만 한다. 전문 용어를 쓰지 않는다.
- 반말/명령조를 피하고 정중하게 존댓말을 쓴다.
- 아래 "신호 사전"을 참고해 사용자의 마지막 답변에서 어떤 신호가 감지됐는지 판단한다.
- 이미 감지된 신호와 겹치지 않는 새로운 정보를 얻을 수 있는 질문을 이어간다.
- 최대 5턴 안에 충분한 정보(경험 1개 이상, 근무조건 1개 이상, 관심업무 1개 이상)가 모이면 ready_to_recommend를 true로 하고 next_question은 빈 문자열로 둔다.
"""


def next_turn(
    question_hints: List[Dict],
    history: List[Dict],
    current_question: Optional[str],
    last_answer: Optional[str],
) -> dict:
    """history: [{"question": str, "answer": str}, ...] 과거(완료된) 턴들.
    current_question/last_answer는 이번에 방금 주고받은 질문-답변 쌍(세션 시작이면 둘 다 None)."""
    payload = {
        "signal_dictionary": question_hints,
        "conversation_so_far": history,
        "question_just_asked": current_question,
        "latest_user_answer": last_answer,
    }
    user_content = json.dumps(payload, ensure_ascii=False)
    if last_answer is None:
        user_content += "\n\n지금은 대화 시작 시점이다. detected_option_codes는 빈 배열로 하고, 첫 질문(next_question)만 생성하라."
    return _call_tool(LLM1_SYSTEM, user_content, LLM1_TOOL)


LLM2_SYSTEM = """\
너는 '희망직종 길잡이' 키오스크의 직무 추천 엔진(LLM2)이다.
대상은 50~60대 이상 구직자다. 아래 제공되는 "후보 직무 카테고리"와 "실제 직업 목록"에 있는 것만 추천해야 하며,
목록에 없는 직업명을 지어내면 안 된다(환각 금지).

각 추천에는 사용자의 답변 중 어떤 부분 때문에 이 직무를 골랐는지 쉬운 말로 이유를 적는다.
counselor_summary는 상담원이 전산 입력 전에 참고할 3~4문장짜리 요약으로, 구직자의 특징과 추천 방향을 담는다.
"""


def recommend(
    conversation: List[Dict],
    job_categories: List[Dict],
    candidate_koeco_jobs: List[Dict],
    rule_based_scores: List[Dict],
) -> dict:
    payload = {
        "conversation": conversation,
        "job_categories": job_categories,
        "candidate_real_jobs": candidate_koeco_jobs,
        "rule_based_signal_scores": rule_based_scores,
    }
    user_content = json.dumps(payload, ensure_ascii=False)
    return _call_tool(LLM2_SYSTEM, user_content, LLM2_TOOL)
