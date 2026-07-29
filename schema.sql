-- 희망직종 길잡이 - 직무 카테고리 샘플 DB (F-009)
-- PRD v0.1 기준: 규칙 기반 매칭에 필요한 최소 스키마

PRAGMA foreign_keys = ON;

-- 직무 카테고리 (화면5 추천 결과에 나오는 단위)
CREATE TABLE job_categories (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    name              TEXT NOT NULL UNIQUE,      -- 예: '사무보조/자료입력'
    easy_description  TEXT NOT NULL,             -- 예: '앉아서 서류를 정리하거나 간단한 컴퓨터 입력을 하는 일입니다.'
    koeco_code        TEXT,                      -- 한국고용직업분류 코드 (참고용, 선택)
    created_at        TEXT NOT NULL DEFAULT (datetime('now'))
);

-- 질문 선택지 마스터 (화면2 해본 일 / 화면3 근무조건 / 화면4 관심업무)
CREATE TABLE question_options (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    screen      TEXT NOT NULL CHECK (screen IN ('experience', 'condition', 'interest')),
    code        TEXT NOT NULL UNIQUE,    -- 예: 'EXP_OFFICE', 'COND_NO_STANDING'
    label       TEXT NOT NULL,           -- 화면에 보이는 문구
    sort_order  INTEGER NOT NULL DEFAULT 0
);

-- 선택지 -> 직무 카테고리 점수 매핑 (규칙 기반 추천의 핵심 테이블)
CREATE TABLE job_category_scores (
    job_category_id INTEGER NOT NULL REFERENCES job_categories(id),
    option_id       INTEGER NOT NULL REFERENCES question_options(id),
    score           INTEGER NOT NULL,        -- 양수: 가점, 음수: 감점 (예: 무거운 물건 어려움 -> 생산직 감점)
    reason_text     TEXT,                    -- 추천 이유 문장에 쓰일 근거 (화면5 "추천 이유")
    PRIMARY KEY (job_category_id, option_id)
);

-- 상담원용 추가 확인 질문 (화면6)
CREATE TABLE consultant_questions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    job_category_id INTEGER NOT NULL REFERENCES job_categories(id),
    question_text   TEXT NOT NULL,
    sort_order      INTEGER NOT NULL DEFAULT 0
);

-- 전산 입력 참고 키워드 후보 (화면6)
CREATE TABLE consultant_keywords (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    job_category_id INTEGER NOT NULL REFERENCES job_categories(id),
    keyword         TEXT NOT NULL
);

CREATE INDEX idx_scores_option ON job_category_scores(option_id);
CREATE INDEX idx_scores_category ON job_category_scores(job_category_id);
CREATE INDEX idx_options_screen ON question_options(screen);
