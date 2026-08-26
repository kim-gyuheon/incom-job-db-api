# 희망직종 길잡이 API

키오스크에서 음성으로 5개 질문에 답하면, 그 답변을 바탕으로 어울리는 직무를 추천해주는
백엔드 API. FastAPI + SQLite 기반이며, 50~60대 이상 구직자가 상담원 도움을 받으며 공용
단말에서 사용하는 상황을 기준으로 설계돼 있다.

## 무엇을 하는 서비스인가

1. 방문자마다 상담 세션을 하나 만든다.
2. "하기 어려운 일이 있으신가요?" 등 고정된 5개 질문(C~G)에 마이크로 답하면, 음성을
   텍스트로 바꾸고(STT) 답변에서 직무 관련 키워드(태그)를 추출해 저장한다.
3. D/E/F(경험·희망·자신 있는 일) 답변으로 사용자 벡터를 만들고, 538개 국가직무 데이터와
   코사인 유사도로 비교해 상위 5개를 추천한다. C(어려운 일)와 G(자격증 여부)는 추천에서
   특정 직무를 제외하는 필터로 쓰인다.
4. `/api/jobs`, `/api/categories`로 전체 직무 목록도 별도로 조회할 수 있다(추천과 무관하게
   프런트가 카탈로그 화면에 쓰는 용도).

## 빠른 시작

```bash
cd api
pip install -r requirements.txt
STT_PROVIDER=mock uvicorn main:app --reload
```

`STT_PROVIDER=mock`은 마이크 없이 질문별 고정 문장으로 전체 흐름을 빠르게 확인할 때 쓴다.
실제 음성 인식까지 로컬에서 보려면 `STT_PROVIDER=openai`(+`OPENAI_API_KEY`)로 띄우면
된다. 서버가 뜨면 `http://127.0.0.1:8000/docs`에서 API 문서를 바로 볼 수 있다.

## 폴더 구조

```
api/                음성 상담 + 직무 조회 API 본체
  main.py            FastAPI 앱, CORS, 에러 핸들러, /api/jobs·/api/categories
  voice.py            음성 상담 3개 엔드포인트(세션/답변/추천)
  voice_db.py          세션·답변·추천 저장, 스키마 보정, 만료 정리
  voice_engine.py       82축 코사인 유사도 매칭 + 자격 게이트 필터
  voice_llm.py           G(자격증) 태그 추출, 추천 이유 문장 생성(Claude 선택적)
  tagging.py               C/D/E/F 답변에서 태그를 뽑는 규칙 기반 정규식 추출기
  vectorizing.py             태그 -> 82축 벡터 변환
  stt.py                      음성 -> 텍스트 변환 (openai/mock)
  db.py, models.py             SQLite 커넥션, /api/jobs 조회 SQL, pydantic 스키마

engine/             538개 직무의 82축 벡터·barrier 데이터를 다루는 매칭 엔진
  matching_engine.py  코사인 유사도 계산(축 개수와 무관하게 동작)
  job_repository.py     CSV -> 직무 카탈로그 로딩, barrier 하드필터 적용
  career_config.py, job_source.py   축 정의, CSV 파싱, barrier 판정 로직

data/               직무 82축 벡터(CSV), barrier 판정 데이터(CSV)
reports/            태그 -> 82축 가중치, 태그 키워드 사전(JSON)
job.db              SQLite 데이터베이스(직무·카테고리·세션 테이블)
tests/              pytest 테스트(아래 "테스트" 참고)
render.yaml         Render 배포 설정
```

## 동작 방식

### 1. 세션

`POST /api/sessions`로 세션을 만들면 `sessionId`와 만료 정책(`idleTimeoutSeconds=120`,
`maxTtlSeconds=1200`)을 받는다. 이후 두 엔드포인트는 이 `sessionId`를 경로에 넣어 호출한다.
세션은 유휴 120초 또는 생성 후 1200초가 지나면 자동 만료되고, `DELETE /api/sessions/{id}`로
언제든 즉시 종료할 수도 있다(존재하지 않거나 이미 끝난 세션에 호출해도 204를 반환하는
멱등 삭제). 만료되거나 종료된 지 1시간이 지난 세션은 다음 `POST /api/sessions` 호출 때
전사문·추천 데이터와 함께 자동으로 정리된다(무기한 보관하지 않음).

### 2. 음성 답변 — `POST /api/sessions/{sessionId}/voice-answers`

질문 5개는 고정돼 있다.

| questionKey | 질문 | 추천에서의 역할 |
| --- | --- | --- |
| C | 하기 어려운 일이 있으신가요? | 해당 태그가 걸린 직무를 barrier로 제외 |
| D | 예전에 어떤 일을 해보셨나요? | 긍정 신호(사용자 벡터에 더해짐) |
| E | 앞으로 어떤 일을 하고 싶으신가요? | 긍정 신호 |
| F | 어떤 일에 자신이 있으신가요? | 긍정 신호 |
| G | 가지고 계신 자격증이 있으신가요? | "없음"이면 자격증 필요 직무 제외 |

오디오(base64 인코딩)를 보내면 STT로 전사한 뒤, C/D/E/F는 `tagging.py`의 규칙 기반
정규식 추출기(부정어 처리 포함, LLM 불필요)로, G는 `voice_llm.py`(Claude API가 있으면
사용, 없으면 표현 사전 기반 규칙 매칭)로 태그를 뽑아 저장한다. 말이 하나도 안 잡히면
오류 대신 `status: "no_speech"`로 200을 돌려줘서 다시 말하게 유도한다. 같은 질문을 다시
답하면 이전 답변은 비활성화되고 새 답변으로 대체된다(수정).

### 3. 추천 — `POST /api/sessions/{sessionId}/voice-recommendations`

D/E/F에서 뽑힌 태그를 82축(성격 16 + 지식중요도 33 + 지식수준 33) 벡터로 변환하고,
538개 직무의 82축 벡터와 코사인 유사도를 계산해 상위 5개를 추천한다. 그 전에 두 단계
필터를 거친다:

- **barrier 하드필터** — C에서 잡힌 태그(예: 야간근무 어려움)가 제외 대상으로 걸린
  직무를 후보에서 뺀다(`data/barrier-review-combined.csv`, 538개 직무 전체에 대한
  제외 판정 1011건).
- **자격 게이트 필터** — 자격증·시험·학위가 있어야 하는 직군(의사, 판사, 연구원,
  관리직 등)은 애초에 추천 후보(`is_voice_recommendable`)에서 빠져 있다. 순수
  코사인 유사도만 쓰면 "돌봄 경험" 답변에 안과의사가 추천되는 식의 오추천이 실측으로
  확인돼서 넣은 필터다(자세한 목록은 `api/voice_engine.py`의
  `EXCLUDED_CATEGORY_LEVELS`/`EXCLUDED_JOB_NAMES` 참고). 538개 중 318개가 최종
  후보로 남는다.
- G에서 "자격증 없음"만 잡히면 `requires_cert=1`인 직무도 추가로 제외한다.

긍정 신호 태그가 하나도 안 잡혔거나 필터링 후 후보가 하나도 안 남으면, 자격증 불필요한
직무 우선으로 기본 추천(`isFallback: true`)을 돌려준다. D/E/F 중 최소 한 문항도 없으면
`MISSING_ANSWERS`(400) 오류를 낸다.

### 4. 직무 목록 조회 — `GET /api/jobs`, `GET /api/categories`

추천과 무관하게 직무 카탈로그를 조회하는 엔드포인트. `categoryIds`로 대분류 필터링,
`recommendableOnly=true`로 사람이 직접 검수한 27개 파일럿 직무만 볼 수 있다(추천
엔드포인트가 쓰는 318개 후보군과는 다른, 별도로 관리되는 플래그다).

### 음성 인식(STT)

`STT_PROVIDER` 환경변수로 공급자를 고른다.

| 값 | 동작 | 비용 |
| --- | --- | --- |
| `openai` (기본 운영 방식) | `OPENAI_API_KEY`로 Whisper API 호출 | 요청당 과금 |
| `mock` | 질문별 고정 문장 반환 | 없음(테스트용) |
| 미설정 | `STT_UNAVAILABLE`(503) 오류 | - |

2026-08-26: 원래는 과금을 피하려고 `faster-whisper`를 같은 프로세스에서 직접 돌리는
`local` 경로가 기본값이었다. Render 무료 플랜 메모리 한도(512MB)와 실사용(마이크) 인식
품질 사이에서 계속 트레이드오프에 시달린 끝에 `openai`로 완전히 전환하기로 결정하고
`local` 경로/`faster-whisper` 의존성 자체를 코드에서 제거했다.

## API 오류 형식

모든 오류는 `{"detail": {"errorCode", "message", "questionKey", "missing"}}` 형태다.

| HTTP | errorCode | 언제 |
| --- | --- | --- |
| 400 | `VALIDATION_ERROR` | 요청 본문 형식이 맞지 않음 |
| 400 | `INVALID_QUESTION_KEY` | `questionKey`가 C/D/E/F/G가 아님 |
| 400 | `INVALID_AUDIO` | `audio.data`가 base64로 해석되지 않거나 비어 있음 |
| 400 | `UNSUPPORTED_AUDIO_ENCODING` | `audio.encoding`이 base64가 아님 |
| 400 | `MISSING_ANSWERS` | 추천에 필요한 답변 부족 |
| 404 | `SESSION_NOT_FOUND` | 세션 id가 없음 |
| 410 | `SESSION_EXPIRED` | 유휴/최대 시간 초과 또는 명시적 종료 |
| 413 | `AUDIO_TOO_LONG` / `AUDIO_TOO_LARGE` | 60초 / 10MB 초과 |
| 415 | `UNSUPPORTED_AUDIO_FORMAT` | webm/ogg/mp4/m4a/mp3/wav 외 |
| 502 | `STT_FAILED` | 음성 인식 실패 |
| 503 | `STT_UNAVAILABLE` | STT 공급자 미설정 |

## 환경변수

`api/.env.example` 참고. 전부 선택사항이며, 안 넣으면 규칙 기반 폴백으로 동작한다.

- `STT_PROVIDER` — `openai`(기본 운영 방식) / `mock`. 미설정 시 음성 답변이 503을 반환.
- `OPENAI_API_KEY`, `STT_MODEL` — `STT_PROVIDER=openai`일 때 필요(기본 경로라 사실상 필수).
- `ANTHROPIC_API_KEY` — G(자격증) 태그 추출과 추천 이유 문장 생성에 보조로 사용. 없으면 규칙 기반으로 동작.

## 테스트

```bash
pip install -r requirements-dev.txt
pytest tests/ -q
```

- `tests/test_voice_engine.py` — 직무명 크로스워크(538/538), `/api/jobs`용 기존
  `is_recommendable`(27개) 불변, 부팅 재실행 멱등성, barrier 하드필터 실제 제외, 무신호
  시 폴백, 자격 게이트 필터가 의사·판사·연구원 등을 실제로 제외하는지.
- `tests/test_sessions.py` — 세션 즉시 종료, 종료 멱등성, 만료 데이터 정리(유예 기간
  경계, 대량 삭제 시에도 안전한지).
- `tests/test_stt.py` — STT 공급자 선택 로직, 빈 오디오 처리, 동시 요청 시 모델이
  한 번만 로드되는지(락 검증).

전부 커밋된 `job.db`를 임시 사본으로 복사해서 실행하므로 원본 파일은 건드리지 않는다.

## 알려진 한계

- 새로 추천 후보가 된 511개(538 - 27개 파일럿) 직무 중 `easyName`/`one_line_desc`는
  182개까지 실데이터(wagework.go.kr 직업 검색 API 직접 호출 + repo에 이미 있던
  koeco_seed.sql)로 채웠다. 나머지 109개는 wagework.go.kr에 대응하는 대표직업이
  없거나(291개 세분류가 537개 대표직업보다 더 촘촘해서 발생) 매칭된 항목의 설명이
  실제 직무와 맞지 않아 비워뒀다 — 예상으로 채우지 않았다.
- `requiresCert`/`certNote`는 27개 파일럿(4건) + 실데이터로 확인한 8건
  (사회복지사·보육교사·이용사·미용사·사서·청소년지도사·부동산중개인·간호조무사) —
  총 12건만 채워져 있다. 나머지 ~500여 개는 실제로 자격증이 필요해도 G(자격증 없음)
  답변으로 안 걸러진다 — 전수 조사는 아직이다.
- 자격 게이트 필터는 카테고리 단위로 보수적으로 잡은 1차 조치였는데, 그중 과잉 제외로
  확인된 2건(법률사무원·간호조무사)만 `ALLOWED_EXCEPTIONS`로 되돌렸다 — 카테고리째
  제외된 202개 전체를 개별 심사한 건 아니라서 나머지 중에도 과잉 제외가 남아있을 수
  있고, 반대로 비제외 카테고리 안에 개별 자격증이 필요한 직업이 여전히 새어 있을 수도
  있다.
- 82축 코사인 유사도는 후보 320여 개 안에서 0.80~0.99 구간에 뭉쳐 구별력이 약하다 —
  매칭된 경험 태그의 KECO 카테고리와 후보 카테고리가 겹치면 가산점을 주는 boost로
  일부(농사·경비 등) 크게 개선했지만, 데이터가 원래 적은 카테고리(육아돌봄 등)는
  boost로 밀어올릴 후보 자체가 부족해 여전히 약하다 — 근본적으로는 82축 가중치
  설계를 다시 봐야 하는 문제.
- barrier 태그(16개) 중 이름이 정확히 겹치는 3개만 barrier-review-combined.csv와
  매칭됐었는데(computer_use처럼 실제 제외 데이터가 있어도 이름이 안 맞아 무시됨),
  9개는 `BARRIER_ID_ALIASES`로 다시 연결했다. CSV 쪽에 대응 항목 자체가 없는 5개
  (walk_long/bend_often/fast_pace/cold_hot_env/customer_conflict)는 여전히 실제
  제외 데이터가 없다 — barrier-review 데이터를 새로 만들어야 하는 후속 과제.
- STT를 `local`(faster-whisper, 무과금)에서 `openai`(요청당 과금)로 완전히 전환했다 —
  Render 무료 플랜 메모리 한도와 실사용 인식 품질 사이의 트레이드오프에서 벗어나기
  위한 결정. 실사용량이 늘어나면 과금이 쌓인다는 점은 감안해야 한다.
- `sessionId`가 URL 경로에 있어서 표준 웹서버 접근 로그에 남는다 — 세션이 최대 1200초
  짜리 단기값이라는 전제로 낮은 위험으로 보고 있다.
