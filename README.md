# incom-job-db-api (KNOW 82축 엔진 이식판)

원본: [`kim-gyuheon/incom-job-db-api`](https://github.com/kim-gyuheon/incom-job-db-api) —
백엔드팀이 구현·배포한 "희망직종 길잡이" API. 이 fork는 그 위에 `skillmatch-voice-backend`의
KNOW 82축 매칭 엔진 + barrier 하드필터 + 538개 직무 전체 데이터를 이식한 버전이다.

## 뭘 바꿨나

기존 구조(FastAPI 앱, 세션 관리, STT 추상화, CORS, 에러 처리, LLM/규칙 기반 폴백 설계)는
**그대로 유지**했다. 바뀐 건 음성 답변 3개 엔드포인트 중 **채점 로직 하나**뿐이다.

| | 원본 | 이 fork |
|---|---|---|
| 추천 후보 직무 | 27개(수작업 태그 완료분) | **538개 전체** |
| 채점 방식 | `job_tags`(REQUIRED/BONUS/EXCLUDE_IF_DIFFICULT, 태그 30개) | **KNOW 82축 코사인 유사도**(`engine/matching_engine.py`) |
| C(하기 어려운 일) 제외 | `job_tags` role='EXCLUDE_IF_DIFFICULT' (27개 직무에만 데이터 있음) | **barrier 하드필터**(`data/barrier-review-combined.csv`, 538개 직무 전체, 제외 판정 1011건) |
| D/E/F(경험/희망/자신) 태그 추출 | LLM 또는 `EXP_*`/`CAN_*` 표현 사전(19개 태그) | **규칙 기반 정규식**(`api/tagging.py`, 26개 태그, 부정어 처리 포함, LLM 불필요) |
| G(자격증) | 그대로 | 그대로(엔진과 무관해서 안 건드림) |

## 어떻게 이식했나

1. `jobs.name`(job.db)과 KNOW 82축 CSV `직업명`이 538개 전부 1:1로 일치함을 먼저 확인
   (같은 KECO/KNOW 국가직업분류 출처라 이름 크로스워크가 100% 신뢰 가능).
2. `api/voice_engine.py`(신규) — 부팅마다(Render 무료 플랜은 배포마다 job.db가 초기화됨,
   기존 `ensure_voice_schema()`와 같은 이유) `voice_job_axis_vectors`(직무별 82축 벡터),
   `voice_job_barrier_excludes`(직무별 제외 barrier), `jobs.is_voice_recommendable` 세 개를
   새로 채운다. **기존 `is_recommendable`/`/api/jobs`는 손대지 않았다** — 이미 배포돼 프론트가
   쓰고 있는 파일럿 27개 목록은 그대로다.
3. `api/voice.py`의 `_score_jobs()`를 걷어내고 `voice_engine.score_and_rank()` 호출로 교체.
   C/D/E/F 태그 추출도 `api/tagging.py`(규칙 기반, LLM 불필요)로 교체했다. G만 원본 그대로.
4. `engine/`, `api/tagging.py`, `api/vectorizing.py`, `data/`, `reports/`는
   `skillmatch-voice-backend`에서 그대로 가져왔다(로직 수정 없음).

## 자동 테스트

```bash
pip install -r requirements-dev.txt
pytest tests/ -q
```

`tests/test_voice_engine.py` 6개: 크로스워크 538/538, 기존 `is_recommendable`(27개) 불변,
부팅 재실행 멱등성, barrier 하드필터 실제 제외, 무신호 시 폴백, 태그 추출 카테고리 분리.
매번 커밋된 `job.db`를 임시 사본으로 복사해서 실행하므로 원본 파일은 건드리지 않는다.

## 로컬 실행(서버)

```bash
cd api
pip install -r requirements.txt
STT_PROVIDER=mock uvicorn main:app --reload
```

세션 생성 → C/D/E/F/G 답변 → 추천까지 전체 플로우를 mock STT로 직접 실행해서 확인:
- `voice_job_axis_vectors`/`is_voice_recommendable`: 538/538 매칭 (크로스워크 100%)
- barrier 제외 판정 1011건 정상 반영(예: `night_shift` 태그가 28개 직무를 제외)
- 추천 결과에 **기존 27개 밖의 직무**(웹기획자, 통계사무원, 사서 등)가 정상적으로 나옴 →
  538개 확장이 실제로 동작함을 확인
- `/api/jobs?recommendableOnly=true` = 27, `/api/categories` = 10 — **기존 엔드포인트 응답
  불변** 확인(회귀 없음)
- `/openapi.json` 정상 생성

## 알려진 한계 (병합 전에 인지해야 할 것)

- **`easyName`/`description`/`requiresCert`/`certNote`는 기존 27개 직무만 실제 값이 채워져
  있다.** 새로 편입된 ~511개는 이 필드들이 비어 있거나(easyName/description → null,
  프론트 계약상 Optional이라 깨지진 않음) `requiresCert`가 부정확할 수 있다(538개 중
  `requires_cert=1`은 4건뿐 — 사람이 27개만 채운 값). **G(자격증 없음) 제외 필터가 새
  511개 직무에는 사실상 적용되지 않는다** — 실제 자격증이 필요한 직업이 추천될 수 있다.
  전체 538개에 대한 requires_cert/cert_note/easyName/description 실사가 후속 과제로 남는다.
- `session_answers`/`question_options`(기존 구조화 답변 테이블)는 C/D/E/F 답변에 대해서는
  더 이상 채워지지 않는다(태그 어휘가 바뀌어서). G만 기존대로 채워진다. **확인 결과 이
  두 테이블은 `api/` 안 어디서도 다시 읽어가지 않는다**(쓰기 전용, grep으로 확인) — 지금
  당장은 영향 없음. 나중에 admin 화면 등에서 이 테이블을 읽는 기능을 추가한다면 그때
  다시 고려하면 된다.
- 82축 코사인 유사도는 의미상 완벽히 들어맞지 않는 직무도 상위에 올라올 수 있다(예:
  "사무실 자료 입력" 답변에 "웹기획자"가 나온 사례 확인) — `skillmatch-voice-backend`에서도
  동일하게 나타나는, 이 매칭 방식 자체의 특성이다.

## 원본 대비 안 건드린 것

`GET /api/jobs`, `GET /api/categories`, CORS 설정, 세션 만료 정책(유휴 120초/최대 1200초),
STT 공급자 추상화(mock/openai), 에러 응답 포맷, `voice_llm.py`의 LLM/규칙 폴백 설계 —
전부 원본 그대로다.
