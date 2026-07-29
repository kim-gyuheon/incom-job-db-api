-- LLM1이 대화 중 각 신호를 자연스럽게 파악하도록 돕는 힌트

UPDATE question_options SET llm_hint = v.hint FROM (
    SELECT 'EXP_OFFICE' AS code, '전에 사무실이나 회사에서 서류·문서 작업을 해보셨는지 자연스럽게 물어보세요.' AS hint
    UNION ALL SELECT 'EXP_SALES', '가게나 매장에서 손님을 상대하거나 물건을 판매해본 경험이 있는지 물어보세요.'
    UNION ALL SELECT 'EXP_KITCHEN', '식당이나 주방에서 일해본 경험이 있는지 물어보세요.'
    UNION ALL SELECT 'EXP_CLEAN', '청소나 건물 관리 관련 일을 해보셨는지 물어보세요.'
    UNION ALL SELECT 'EXP_DRIVE', '운전면허가 있거나 배송·운전 관련 일을 해보셨는지 물어보세요.'
    UNION ALL SELECT 'EXP_FACTORY', '공장이나 생산 현장에서 일해본 경험이 있는지 물어보세요.'
    UNION ALL SELECT 'EXP_CARE', '어르신이나 아이를 돌봐본 경험(가족 포함)이 있는지 물어보세요.'
    UNION ALL SELECT 'EXP_NONE', '특별히 해본 일이 별로 없다고 답하면 이 신호로 기록하고, 부담 갖지 않도록 안심시키는 말을 함께 해주세요.'
    UNION ALL SELECT 'EXP_UNKNOWN', '경험을 딱히 떠올리지 못하면 다음 질문(근무조건)으로 자연스럽게 넘어가세요.'
    UNION ALL SELECT 'COND_NO_STANDING', '오래 서서 하는 일이 힘든지 부담없이 물어보세요.'
    UNION ALL SELECT 'COND_NO_HEAVY', '무거운 물건을 드는 일이 가능한지 물어보세요.'
    UNION ALL SELECT 'COND_PEOPLE_OK', '사람을 상대하거나 대화하는 일이 괜찮은지 물어보세요.'
    UNION ALL SELECT 'COND_COMPUTER', '컴퓨터나 스마트폰을 어느 정도 다룰 수 있는지 부담없이 물어보세요.'
    UNION ALL SELECT 'COND_DRIVE', '운전이 가능한지, 운전을 즐기는지 물어보세요.'
    UNION ALL SELECT 'COND_SHORT_HOUR', '하루 몇 시간 정도, 혹은 짧은 시간만 일하고 싶은지 근무 희망 시간을 물어보세요.'
    UNION ALL SELECT 'COND_NO_WEEKEND', '주말 근무가 가능한지 물어보세요.'
    UNION ALL SELECT 'COND_UNKNOWN', '근무 조건에 대해 아직 생각해보지 않았다면 다음 질문(관심 업무)으로 넘어가세요.'
    UNION ALL SELECT 'INT_DOC', '서류 정리나 컴퓨터 입력 같은 일에 관심이 있는지 물어보세요.'
    UNION ALL SELECT 'INT_RECEPTION', '손님을 안내하거나 접수하는 일에 관심이 있는지 물어보세요.'
    UNION ALL SELECT 'INT_PACK', '물건을 정리하거나 포장하는 일에 관심이 있는지 물어보세요.'
    UNION ALL SELECT 'INT_SALES', '매장에서 계산하거나 판매를 돕는 일에 관심이 있는지 물어보세요.'
    UNION ALL SELECT 'INT_CLEAN', '청소나 건물 관리하는 일에 관심이 있는지 물어보세요.'
    UNION ALL SELECT 'INT_FOOD', '음식을 준비하거나 설거지하는 일에 관심이 있는지 물어보세요.'
    UNION ALL SELECT 'INT_CARE', '어르신이나 아이를 돌보는 일에 관심이 있는지 물어보세요.'
    UNION ALL SELECT 'INT_DELIVERY', '배달이나 운전하는 일에 관심이 있는지 물어보세요.'
) AS v
WHERE question_options.code = v.code;
