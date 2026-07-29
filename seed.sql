-- 직무 카테고리 샘플 데이터 (PRD 화면2~6 예시 기준)

INSERT INTO job_categories (name, easy_description) VALUES
    ('사무보조/자료입력', '앉아서 서류를 정리하거나 간단한 컴퓨터 입력을 하는 일입니다.'),
    ('접수/안내',         '손님을 맞이하고 안내하거나 전화를 받는 일입니다.'),
    ('매장관리/판매보조', '매장에서 물건을 정리하고 손님 계산을 돕는 일입니다.'),
    ('청소/건물관리',     '건물이나 시설을 청소하고 정리하는 일입니다.'),
    ('생산/물류',         '공장이나 창고에서 물건을 만들거나 정리, 포장하는 일입니다.'),
    ('배송/운전',         '차량으로 물건을 배달하거나 운전하는 일입니다.'),
    ('돌봄',              '어르신이나 아이를 보살피는 일입니다.'),
    ('주방/음식준비',     '음식을 준비하거나 설거지를 하는 일입니다.');

-- 화면2: 해본 일 / 할 수 있는 일
INSERT INTO question_options (screen, code, label, sort_order) VALUES
    ('experience', 'EXP_OFFICE',  '사무/문서 작업',        1),
    ('experience', 'EXP_SALES',   '판매/매장 일',          2),
    ('experience', 'EXP_KITCHEN', '음식점/주방 일',        3),
    ('experience', 'EXP_CLEAN',   '청소/미화',             4),
    ('experience', 'EXP_DRIVE',   '운전/배송',             5),
    ('experience', 'EXP_FACTORY', '생산/공장',             6),
    ('experience', 'EXP_CARE',    '돌봄/간병',             7),
    ('experience', 'EXP_NONE',    '해본 일이 거의 없음',   8),
    ('experience', 'EXP_UNKNOWN', '잘 모르겠어요',         9);

-- 화면3: 근무 조건
INSERT INTO question_options (screen, code, label, sort_order) VALUES
    ('condition', 'COND_NO_STANDING', '오래 서 있는 일은 어려워요',      1),
    ('condition', 'COND_NO_HEAVY',    '무거운 물건을 드는 일은 어려워요', 2),
    ('condition', 'COND_PEOPLE_OK',   '사람을 만나는 일도 괜찮아요',      3),
    ('condition', 'COND_COMPUTER',    '컴퓨터는 조금 할 수 있어요',       4),
    ('condition', 'COND_DRIVE',       '운전할 수 있어요',                5),
    ('condition', 'COND_SHORT_HOUR',  '짧은 시간 일하고 싶어요',         6),
    ('condition', 'COND_NO_WEEKEND',  '주말 근무는 어려워요',            7),
    ('condition', 'COND_UNKNOWN',     '잘 모르겠어요',                   8);

-- 화면4: 관심 업무
INSERT INTO question_options (screen, code, label, sort_order) VALUES
    ('interest', 'INT_DOC',       '서류 정리, 간단한 컴퓨터 입력', 1),
    ('interest', 'INT_RECEPTION', '손님 안내, 접수',              2),
    ('interest', 'INT_PACK',      '물건 정리, 포장',              3),
    ('interest', 'INT_SALES',     '매장 계산, 판매 보조',         4),
    ('interest', 'INT_CLEAN',     '청소, 건물 관리',              5),
    ('interest', 'INT_FOOD',      '음식 준비, 설거지',            6),
    ('interest', 'INT_CARE',      '어르신/아이 돌봄',             7),
    ('interest', 'INT_DELIVERY',  '배달, 운전',                   8);

-- 점수 매핑: PRD 13.3 예시 규칙 반영
-- 사무보조/자료입력
INSERT INTO job_category_scores (job_category_id, option_id, score, reason_text)
SELECT jc.id, qo.id, v.column3, v.column4 FROM (VALUES
    ('사무보조/자료입력', 'EXP_OFFICE',      3, '사무/문서 작업 경험이 있다고 답하셨습니다.'),
    ('사무보조/자료입력', 'COND_COMPUTER',   2, '컴퓨터를 조금 사용할 수 있다고 답하셨습니다.'),
    ('사무보조/자료입력', 'COND_NO_STANDING',1, '오래 서 있는 일은 어렵다고 답하셨습니다.'),
    ('사무보조/자료입력', 'INT_DOC',         3, '서류 정리, 간단한 컴퓨터 입력에 관심이 있다고 답하셨습니다.'),

    ('접수/안내', 'EXP_SALES',       2, '판매/매장 일 경험이 있다고 답하셨습니다.'),
    ('접수/안내', 'COND_PEOPLE_OK',  2, '사람을 만나는 일도 괜찮다고 답하셨습니다.'),
    ('접수/안내', 'COND_NO_STANDING',1, '오래 서 있는 일은 어렵다고 답하셨습니다.'),
    ('접수/안내', 'INT_RECEPTION',   3, '손님 안내, 접수에 관심이 있다고 답하셨습니다.'),

    ('매장관리/판매보조', 'EXP_SALES',        3, '판매/매장 일 경험이 있다고 답하셨습니다.'),
    ('매장관리/판매보조', 'COND_PEOPLE_OK',   2, '사람을 만나는 일도 괜찮다고 답하셨습니다.'),
    ('매장관리/판매보조', 'INT_SALES',        3, '매장 계산, 판매 보조에 관심이 있다고 답하셨습니다.'),
    ('매장관리/판매보조', 'COND_NO_STANDING', -1, '오래 서 있는 일이 많아 다소 맞지 않을 수 있습니다.'),

    ('청소/건물관리', 'EXP_CLEAN',        3, '청소/미화 경험이 있다고 답하셨습니다.'),
    ('청소/건물관리', 'INT_CLEAN',        3, '청소, 건물 관리에 관심이 있다고 답하셨습니다.'),
    ('청소/건물관리', 'COND_NO_STANDING', -1, '오래 서 있는 일이 많아 어려울 수 있습니다.'),

    ('생산/물류', 'EXP_FACTORY',  3, '생산/공장 경험이 있다고 답하셨습니다.'),
    ('생산/물류', 'INT_PACK',     2, '물건 정리, 포장에 관심이 있다고 답하셨습니다.'),
    ('생산/물류', 'COND_NO_HEAVY',-2, '무거운 물건을 드는 일은 어렵다고 답하셨습니다.'),

    ('배송/운전', 'EXP_DRIVE',    3, '운전/배송 경험이 있다고 답하셨습니다.'),
    ('배송/운전', 'COND_DRIVE',   3, '운전할 수 있다고 답하셨습니다.'),
    ('배송/운전', 'INT_DELIVERY', 3, '배달, 운전에 관심이 있다고 답하셨습니다.'),
    ('배송/운전', 'COND_NO_HEAVY',-1, '무거운 물건을 드는 일은 어려울 수 있습니다.'),

    ('돌봄', 'EXP_CARE',      3, '돌봄/간병 경험이 있다고 답하셨습니다.'),
    ('돌봄', 'INT_CARE',      3, '어르신/아이 돌봄에 관심이 있다고 답하셨습니다.'),
    ('돌봄', 'COND_PEOPLE_OK',1, '사람을 만나는 일도 괜찮다고 답하셨습니다.'),

    ('주방/음식준비', 'EXP_KITCHEN',     3, '음식점/주방 일 경험이 있다고 답하셨습니다.'),
    ('주방/음식준비', 'INT_FOOD',        3, '음식 준비, 설거지에 관심이 있다고 답하셨습니다.'),
    ('주방/음식준비', 'COND_NO_STANDING',-1, '오래 서 있는 일이 많아 어려울 수 있습니다.')
) AS v
JOIN job_categories jc ON jc.name = v.column1
JOIN question_options qo ON qo.code = v.column2;

-- 상담원용 추가 확인 질문 (화면6 예시)
INSERT INTO consultant_questions (job_category_id, question_text, sort_order)
SELECT jc.id, v.column2, v.column3 FROM (VALUES
    ('사무보조/자료입력', '엑셀이나 한글 문서 작업 경험이 있나요?', 1),
    ('사무보조/자료입력', '전화 응대가 가능한가요?', 2),
    ('사무보조/자료입력', '하루 몇 시간 근무를 원하시나요?', 3),
    ('사무보조/자료입력', '앉아서 하는 업무를 선호하시나요?', 4),
    ('접수/안내', '전화 응대가 가능한가요?', 1),
    ('접수/안내', '하루 몇 시간 근무를 원하시나요?', 2)
) AS v
JOIN job_categories jc ON jc.name = v.column1;

-- 전산 입력 참고 키워드 후보 (화면6 예시)
INSERT INTO consultant_keywords (job_category_id, keyword)
SELECT jc.id, v.column2 FROM (VALUES
    ('사무보조/자료입력', '사무보조'),
    ('사무보조/자료입력', '자료입력'),
    ('접수/안내', '접수안내'),
    ('매장관리/판매보조', '매장관리'),
    ('매장관리/판매보조', '판매보조'),
    ('청소/건물관리', '청소'),
    ('청소/건물관리', '건물관리'),
    ('생산/물류', '생산직'),
    ('생산/물류', '물류'),
    ('배송/운전', '배송'),
    ('배송/운전', '운전'),
    ('돌봄', '돌봄서비스'),
    ('주방/음식준비', '주방보조')
) AS v
JOIN job_categories jc ON jc.name = v.column1;
