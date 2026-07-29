-- 한국고용직업분류(KECO) 실제 직업 데이터 (wagework.go.kr 임금직업포털에서 수집)
-- work.go.kr의 구 직업정보 검색은 서비스 종료, 후속 서비스인 임금직업포털로 이전됨.
-- PRD NG-002(전체 데이터 완벽 구현 안함)에 따라 50~60대 대상 직무와 관련된
-- 2개 대분류(미용·여행·숙박·음식·경비·청소직 / 영업·판매·운전·운송직)만 샘플로 수집.

PRAGMA foreign_keys = ON;

CREATE TABLE koeco_categories (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    name    TEXT NOT NULL UNIQUE   -- 대분류명 (예: '미용·여행·숙박·음식·경비·청소직')
);

CREATE TABLE koeco_jobs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    category_id     INTEGER NOT NULL REFERENCES koeco_categories(id),
    name            TEXT NOT NULL UNIQUE,   -- 직업명 (예: '요양 보호사 및 간병인')
    description     TEXT NOT NULL,          -- 하는 일 (원문 그대로)
    avg_salary_band TEXT,                   -- 평균연봉 구간 (예: '3천만원')
    outlook         TEXT                    -- 미래전망 (예: '증가', '유지', '다소 감소', '감소')
);

-- PRD 화면에서 쓰는 쉬운 직무 카테고리 <-> 실제 KECO 직업 매핑 (N:N)
CREATE TABLE job_category_koeco_jobs (
    job_category_id INTEGER NOT NULL REFERENCES job_categories(id),
    koeco_job_id    INTEGER NOT NULL REFERENCES koeco_jobs(id),
    PRIMARY KEY (job_category_id, koeco_job_id)
);

CREATE INDEX idx_koeco_jobs_category ON koeco_jobs(category_id);
