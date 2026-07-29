-- LLM 대화형 아키텍처 반영 (사용자 ↔ LLM1(질문 특화) ↔ LLM2(직업 추천))
-- 화이트보드 구조: 사용자 -> 질문(LLM1, 질문DB 참고) -> 답변 -> (최대 5턴 반복)
--                 -> LLM2(직업DB 참고) -> 추천직무

PRAGMA foreign_keys = ON;

-- LLM1이 대화 중 이 신호를 왜/어떻게 물어봐야 하는지 참고하는 힌트
-- (question_options은 이제 "고정 버튼"이 아니라 LLM1이 감지하려는 신호 사전 역할)
ALTER TABLE question_options ADD COLUMN llm_hint TEXT;

-- 상담 세션 (사용자 1회 방문 = 1세션)
CREATE TABLE sessions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at    TEXT NOT NULL DEFAULT (datetime('now')),
    status        TEXT NOT NULL DEFAULT '진행중'
                      CHECK (status IN ('진행중', '완료', '상담원전달')),
    counselor_summary TEXT   -- 화면6: 상담원용 요약 문장 (LLM1/LLM2 종합 생성)
);

-- 대화 턴 (화이트보드의 사용자 <-> 답변 루프, 최대 5턴)
CREATE TABLE conversation_turns (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id    INTEGER NOT NULL REFERENCES sessions(id),
    turn_no       INTEGER NOT NULL CHECK (turn_no BETWEEN 1 AND 5),
    question_text TEXT NOT NULL,   -- LLM1이 질문DB를 참고해 실제로 생성한 질문
    user_answer   TEXT NOT NULL,   -- 사용자의 자유 응답(또는 버튼 선택 라벨)
    created_at    TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (session_id, turn_no)
);

-- 이 턴에서 LLM1이 사용자 답변으로부터 감지한 신호(question_options)
-- -> job_category_scores와 연결해 LLM2에게 참고자료로 전달
CREATE TABLE turn_detected_options (
    turn_id   INTEGER NOT NULL REFERENCES conversation_turns(id),
    option_id INTEGER NOT NULL REFERENCES question_options(id),
    PRIMARY KEY (turn_id, option_id)
);

-- LLM2의 최종 추천 결과 (화면5: 추천직무)
CREATE TABLE job_recommendations (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      INTEGER NOT NULL REFERENCES sessions(id),
    job_category_id INTEGER NOT NULL REFERENCES job_categories(id),
    koeco_job_id    INTEGER REFERENCES koeco_jobs(id),   -- LLM2가 매칭한 실제 직업 (선택)
    rank            INTEGER NOT NULL,                     -- 1~3위
    reason_text     TEXT NOT NULL,                        -- LLM2가 생성한 추천 이유
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_turns_session ON conversation_turns(session_id);
CREATE INDEX idx_detected_turn ON turn_detected_options(turn_id);
CREATE INDEX idx_recs_session ON job_recommendations(session_id);
