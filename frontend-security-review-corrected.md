# 보안 검토 리포트 정리본 — skillmatchboard (inbuld_team_a)

> 원본: `report.md` (Codex 기반 AI 보안 스캔, 백엔드 멘토가 실행). 이 문서는 그 리포트를
> 검증·중복 제거·정정한 결과물이다. 원본은 손대지 않고 그대로 뒀다.

## 이 문서를 만든 이유 — 원본 리포트의 구조적 결함

원본 `report.md`(4,183줄)를 열어보면 **Scope, Threat Model, Findings 세 섹션 전부가
같은 내용을 5~8번씩 이어붙인 상태**예요. 스캔 도구가 병렬로 여러 "worker"를 돌린 뒤
합치는 `dedup` 단계가 있는데(원본 155번째 줄에 "dedup-0006 performed serial semantic
aggregation only" 라고 스스로 적어놨어요), 이 단계가 **의미 기준으로 합치지 못하고
글자 그대로 다른 문장만 별개로 취급**해서 사실상 실패했어요.

구체적으로:

- **"세션이 이전 사용자 것 그대로 남는다"는 이슈가 [1][2][3] 세 번** 따로 적혀 있어요.
  세 개 다 같은 파일(`App.tsx`, `TutorialPage.tsx`, `VoiceQuestionPage.tsx`)의 같은
  코드를 가리켜요.
- **"dev-server.log가 개발자 경로를 유출한다"는 이슈가 [4][5][7][8][11] 다섯 번**
  따로 적혀 있어요. 전부 같은 파일, 같은 근본 원인이에요.
- **"콘솔에 전사문·세션ID가 남는다"는 이슈가 [9][10] 두 번** 적혀 있는데, [10]은
  나머지 전부 영어인 문서에 갑자기 한국어로만 적혀 있어요(스캔 도구가 두 언어로 같은
  걸 또 만든 것으로 보여요).
- 그 결과 원본 상단 "Scan Summary" 표는 `Reportable DSS findings: 10`이라고 써있는데,
  **실제 서로 다른 문제는 4개**예요. 이 숫자부터가 틀렸어요.
- Scope/Threat Model 섹션(원본 3~432번째 줄)도 같은 문제예요 — 예를 들어
  `node_modules` 제외 사유 문장("Excluded node_modules/\*\*: ...")이 **원본 안에서만
  35번** 반복돼요.

**정리 방식**: 각 중복 클러스터에서 가장 근거(코드 인용, 정확한 줄 번호, 구체적 수치)가
충실한 버전을 골라 하나로 합쳤고, 서로 다른 클러스터가 각각 언급한 CWE 태그는 합집합으로
유지했어요. 내용을 새로 지어내지 않고 원본에 이미 있던 것 중에서만 골랐어요.

## 이미지로 보내주신 표는 이 리포트가 아니에요

캡처해주신 "우선순위 / 확인된 문제 / 위험 및 수정 방향" 표는 `report.md`를 검색해봐도
안 나와요(`.gitignore`+`.env.example`, "추천 직무 안전 정보 유실"(isRecommendable/
requiresCert/certNote), "수정 취소가 실제 취소가 아님", "테스트·Lint 없음", "저장소
오염"(node_modules/.DS_Store 포함) — 이 항목들은 `report.md`의 11개 finding 어디에도
없어요). 이 리포트가 스캔한 범위 자체가 "Git 메타데이터 없음, 백엔드 없음"이라고 명시돼
있어서(아래 Scope 참고), Git/저장소 위생 관련 항목(P0, 마지막 P2 두 개)은 애초에 이
스캔의 스코프 밖이에요.

즉 **이미지 표는 별도의 (아마 더 폭넓은 범위로 돌린) 리포트**로 보여요. 그 파일도 있으면
같이 주시면 그것도 검증해드릴게요 — 지금은 `report.md` 하나만 받아서 그것만 정리했어요.

---

## Scope

read-only 정적 보안 감사. 대상은 Git 메타데이터가 없는 스냅샷 상태의 React 19/Vite
프런트엔드(`skillmatchboard`) 소스 트리 전체(182개 non-`node_modules` 파일, 그중
TypeScript/TSX/CSS 50~52개). 백엔드 구현, 배포/호스팅 설정, CI, 환경파일은 스코프에
없음(존재하지 않아서 검사 자체가 불가능).

**핵심 제약사항** (원본에 반복 서술된 내용을 하나로 정리):

- **대상이 Git 저장소가 아니다.** 그래서 어떤 파일이 실제로 커밋·원격에 공개됐는지,
  `.env`가 과거에 노출된 적이 있는지는 이 스냅샷만으로 확인 불가능함. (사용자가
  의심하는 "env 업로드 이력"은 이 스캔으로 증명도 반증도 안 됨.)
- 백엔드 소스·DB·인증·배포 설정이 전혀 없어서, 서버 측 통제(세션 소유권, rate limit,
  CORS, TLS, 로그 보존)는 전부 "확인 불가"로 남음 — 프런트만 보고 백엔드를 추정할 수
  없음.
- `node_modules/**`와 폰트 바이너리는 제외(제조사 제공 코드/자산이라 직접 검토 대상
  아님). `package.json`/`package-lock.json`의 registry 출처와 integrity 메타데이터,
  설치 스크립트 유무는 검토함. 실시간 CVE 조회는 오프라인이라 수행 안 함.
- SVG 111개 전부 XML로 파싱해서 script/이벤트 핸들러/외부 참조 여부 확인 — 문제 없음.
- 코드 실행이나 브라우저 런타임 테스트는 하지 않은 **정적 소스 리뷰**임(마이크 동작,
  동시성 이슈는 소스 추론이지 재현 아님).

---

## Threat Model

Skill Match Board는 브라우저에서 백엔드 세션을 생성하고, 최대 60초 WebM/Opus 마이크
녹음을 Base64로 인코딩해 5개 질문에 대한 답변으로 전송하며, STT 결과와 직무 추천을
받아 React 메모리에 세션 상태·전사문·추천·선택 직무를 유지하는 SPA다.
`VITE_API_BASE_URL`이 API 수신자를 결정하지만 저장소 스냅샷엔 유효값이 없다. 안내
문구(도우미 호출)와 최종 화면 자동 종료 타이머로 미루어 **공용/상담용 단말** 사용이
암시되지만 명시적으로 문서화돼 있진 않다.

### Assets (보호 대상)

- 사용자의 원본 마이크 음성과 그 Base64 WebM/Opus 인코딩본
  (`src/pages/VoiceQuestionPage.tsx:13-16,167-214`)
- STT 전사문, 키워드, 신뢰도, 답변 시각, 사용자의 어려움/경험/관심/강점/자격증 답변
  (`src/types/api.ts:57-79`, `src/App.tsx:76-88`)
- 백엔드 발급 `sessionId`와 그에 연결된 서버 측 세션 상태·만료 정보
  (`src/services/sessionApi.ts:8-53`)
- 직무 추천 결과, 추천 이유, 매칭 키워드, 최종 선택 직무의 무결성
  (`src/services/recommendationApi.ts:93-171`)
- 최종 구직신청서 화면에 표시되는 답변 — 공용 화면에서의 프라이버시
  (`src/pages/ResumeGenerationPage.tsx:80-126`)
- `VITE_API_BASE_URL`이 가리키는 API 신뢰 도메인 — 공개 클라이언트 설정이라 비밀값이
  들어가면 안 됨 (`src/services/apiBase.ts:1-3`)
- 백엔드 오류 응답이 전달될 수 있는 브라우저 콘솔 진단 정보
  (`src/services/apiBase.ts:134-143`)
- 개발자 워크스테이션 신원·경로 메타데이터(`dev-server.log`에 남아있음)

### Trust Boundaries (신뢰 경계)

- **사용자 ↔ 브라우저 마이크**: `getUserMedia` 권한이 캡처를 통제. 클라이언트가
  WebM/Opus 지원 확인, 60초 자동 종료, 5초 무음 종료, 스트림 정리를 수행하지만 이건
  전부 클라이언트 UX 통제지 서버 측 남용 방지 통제가 아님.
- **빌드/배포 운영자 → 공개 브라우저 번들**: `VITE_API_BASE_URL`은 trim·후행슬래시
  제거 후 모든 API 요청의 대상이 됨. 호스트/스킴 allowlist는 없음
  (`src/services/apiBase.ts:1-3,77-116`).
- **브라우저 → 세션/음성답변/추천 API**: 3개 엔드포인트 모두 명시적 `Authorization`
  헤더나 인증정보 없이 세션ID만으로 요청. 프런트는 응답 스키마와 `sessionId`/
  `questionKey` 일치 여부만 검증(`src/services/voiceApi.ts:92-133`,
  `src/services/recommendationApi.ts:93-171`).
- **백엔드 오류 응답 → 브라우저 콘솔**: 파싱된 오류 payload가 `ApiRequestError.details`
  에 통째로 보관되고 일부 경로에서 콘솔로 그대로 전달됨(`src/services/apiBase.ts:134-143`).
- **브라우저 메모리 → 화면(다음 사용자/주변인)**: `sessionId`, 전사문, 추천 결과가
  React 상태에만 유지되며 완료 시 초기화, 최종 신청서 화면은 120초 뒤 자동 종료. **단,
  시작 화면으로 돌아가는 경로는 이 초기화를 거치지 않음** (Finding 1 참고).
- **개발 도구 → 저장소 로그**: `dev-server.log`가 Vite 실행 정보와 절대 로컬 경로를
  담은 채 소스 트리 루트에 남아 있고, 이걸 배제할 `.gitignore`가 없음.

### Attacker Capabilities (가정하는 공격자 역량)

- 일반 사용자는 자기 브라우저에서 음성·요청을 임의로 조작 가능(프런트 검증은 보안
  경계가 아님).
- **같은 공용 단말의 다음 사용자**는 이전 사용자가 남긴 브라우저 상태(세션, 전사문,
  화면)에 접근 가능 — 이게 핵심 위협 시나리오.
- 소스 스냅샷/아카이브 수신자는 포함된 로그(`dev-server.log`)와 공개 클라이언트 설정을
  읽을 수 있음.
- 빌드/배포 운영자는 `VITE_API_BASE_URL`을 바꿔 음성·세션 데이터 수신처를 변경할 수
  있음(이미 배포 권한을 가진 행위자로 가정, 별도 위협으로 취급 안 함).
- 백엔드·배포 계정·비밀 저장소·타인의 `sessionId`를 이미 통제한다는 가정은 하지 않음.

### Security Objectives (있어야 할 통제, 정리)

- `VITE_*` 값은 전부 공개 클라이언트 설정으로 취급하고 비밀을 넣지 않는다. `VITE_API_BASE_URL`은 승인된 HTTPS origin에만 바인딩한다.
- 백엔드는 `sessionId`를 충분한 엔트로피로 발급하고, 모든 음성답변/추천 요청에서 소유권·만료·재사용 정책을 독립적으로 검증해야 한다(프런트의 응답 매칭 검사는 방어수단이지 인증이 아님).
- 서버는 클라이언트가 보내는 `durationMs`/`format`/`codec`/`questionKey`를 신뢰하지 않고 실제 업로드 크기·형식·요청 빈도·STT 비용 한도를 자체 집행해야 한다.
- **공용/상담 단말이라면, 화면 전환·오류·유휴 상태 어디서든 이전 사용자의 전사문·신청서가 남지 않도록 상태 초기화 정책을 갖춰야 한다.**
- 브라우저 콘솔과 서버/프록시 로그에 `sessionId`, 음성, 전사문, 원시 오류 payload가 불필요하게 남지 않아야 한다.
- `.env*`, 로컬 로그, `node_modules`, 빌드 산출물은 버전관리에서 제외하고, 예시 파일만 비밀 없는 형태로 유지한다.
- CORS·인증·rate limit은 프런트가 아니라 백엔드/게이트웨이가 소유해야 한다(이번 스코프 밖, 별도 검증 필요).

### Assumptions (전제)

- 현재 스냅샷에는 `.env`/`.env.*` 파일이 없다. 사용자가 언급한 "env 업로드" 의심은 이
  스냅샷에서 재현되지 않으며, Git 이력이나 다른 배포 위치의 사실일 수 있어 **이 스캔만
  으로는 확인도 반증도 안 됨**.
- 현재 스냅샷에는 `.gitignore`가 없고 대상은 Git 저장소가 아니다 — 어떤 파일이 실제
  커밋·공개됐는지 확인 불가.
- 화면 흐름과 안내 문구로 미루어 상담원 보조 하의 공용/키오스크형 단말 사용이 유력하지만
  명시 문서는 없음.

---

## Findings (정리: 원본 11개 instance → 실제 4개)

| # | 문제 | Severity | Confidence |
| --- | --- | --- | --- |
| 1 | 시작 화면으로 돌아가도 이전 사용자의 상담 세션·전사문이 그대로 남음 | **Medium** | High |
| 2 | 번들에 포함된 `dev-server.log`가 개발자 계정 경로를 유출함 | Low | High |
| 3 | 마이크 초기화 실패 시 스트림/AudioContext가 해제 안 될 수 있음 | Low | Medium |
| 4 | 오류 경로에서 전사문·세션 정보가 브라우저 콘솔에 남을 수 있음 | Low | Medium |

원본의 [1][2][3] → 정리본 #1, [4][5][7][8][11] → 정리본 #2, [6] → 정리본 #3,
[9][10] → 정리본 #4로 합침.

---

### [1] 시작 화면으로 돌아가도 이전 사용자의 상담 세션·전사문이 그대로 남음

| Field | Value |
| --- | --- |
| Severity | **Medium** |
| Confidence | High |
| CWE | CWE-613 (Insufficient Session Expiration), CWE-226 (Sensitive Information Uncleared Before Release), CWE-359 (Privacy Violation) |
| Affected lines | `src/App.tsx:41-50, 107-149, 179-192, 320-335`, `src/pages/TutorialPage.tsx:92-110`, `src/pages/VoiceQuestionPage.tsx:227-232,382-390,550-568`, `src/pages/AnswerReviewPage.tsx:45-57`, `src/pages/ResumeGenerationPage.tsx:24-40` |

**요약**: 전사문, 답변 메타데이터, 추천 결과, 백엔드 세션ID가 최상위 `App` 컴포넌트의
React state에 저장된다. 첫 질문 → 튜토리얼 → 공개 시작 화면으로 돌아가는 "뒤로가기"
경로는 기존에 있는 초기화 루틴을 호출하지 않는다. 이 상태에서 "시작"을 누르고 튜토리얼을
건너뛰면 **null이 아닌 기존 세션을 그대로 재사용**하고 이전 답변이 화면에 그대로
표시된다. 게다가 유휴(inactivity) 타이머는 최종 신청서 화면에만 있고 중간 화면들에는
전혀 없다.

**근본 원인**: 상담 세션 종료를 담당하는 단일 지점이 없다. 정리(cleanup)는 정상 완료와
세션 오류 복구 시에만 호출되고, 공개 시작 화면으로 돌아가는 일반적인 경로에서는 호출되지
않는다.

```tsx
// src/App.tsx — 뒤로가기는 초기화를 거치지 않는다
const handleTutorialPrev = () => {
  goToStep('start')   // ← 세션/답변 state를 그대로 둔 채 화면만 전환
}

// 초기화는 오직 정상 완료 시에만 일어난다
const handleResumeComplete = () => {
  goToStep('start')
  setSessionId(null)
  setAnswers(createInitialAnswers())
  setAnswerDetails({})
  // ...
}
```

**위험도**: 공용 상담 단말에서 다음 사용자가 "이전, 시작, 건너뛰기"라는 정상 UI 조작
만으로 이전 사용자의 취업 상담 전사문을 열람·수정하거나 이전 세션 권한을 이어받을 수
있다. 원격 네트워크 공격이 아니라 **같은 화면에 대한 물리적 접근**이 전제조건이라 발생
가능성은 "중간"으로 평가했다(제품 성격상 상담사 동석 공용 단말 사용이 명시적이라 완전히
낮게 볼 순 없음).

**수정 방향**:
1. `App` 레벨에 `endSession`/`reset` 루틴을 하나 만들고, **공개 시작 화면으로 가는
   모든 경로, 명시적 취소, 완료, 세션 오류, 전역 유휴 만료**에서 전부 이 루틴을 거치게
   한다. 진행 중인 세션 생성/음성/추천 요청을 중단(abort)하고, 마이크를 정지하고,
   `sessionId`/답변/추천/선택/편집 상태를 전부 지운 뒤 시작 화면으로 이동해야 한다.
2. 새 상담을 시작할 때는 **항상 새 세션을 발급**해야 한다(기존 세션 재사용 금지).
3. 백엔드가 반환하는 `expiresAt`/`idleTimeoutSeconds`를 실제로 활용해 앱 전역 유휴
   타이머를 두고, 최종 화면에만 있는 지금 구조를 전체 흐름으로 확장한다.
4. 완료/취소/만료 시 서버 세션도 best-effort로 폐기 요청(실패해도 로컬 정리는 반드시
   성공해야 함).

**테스트 체크리스트**:
- 1번 질문 답변 → 이전 → 튜토리얼 이전 → 시작 → 건너뛰기 → 답변이 비어있고 새
  `sessionId`가 발급되는지 확인.
- 시작 화면으로 가는 모든 경로에서 `StartPage`가 렌더링되기 전에 민감 상태가 전부
  지워지는지 확인.
- 녹음/API 호출 도중 리셋·만료가 발생했을 때 트랙 정지, 요청 중단, 늦게 도착하는 응답
  무시가 되는지 확인.

---

### [2] 번들에 포함된 `dev-server.log`가 개발자 계정 경로를 유출함

| Field | Value |
| --- | --- |
| Severity | Low |
| Confidence | High |
| CWE | CWE-200 (Information Exposure), CWE-532 (Insertion of Sensitive Information into Log File) |
| Affected lines | `dev-server.log:2-3, 12-22, 44-59, 751-779, 791-927` |

**요약**: 프로젝트 루트에 934줄(237,581바이트)짜리 Vite 개발 로그가 그대로 남아있고,
`C:/Users/<계정명>/OneDrive/...` 형태의 절대 경로가 반복적으로 기록돼 있다. 이 소스
스냅샷을 전달받는 사람은 누구나 개발자의 Windows 계정명과 로컬 프로젝트/의존성 경로
구조를 그대로 알게 된다. 자격증명·토큰·세션ID 등 더 강한 비밀은 로그 안에서 발견되지
않았다.

**근본 원인**: 런타임에 생성된 로그 파일이 소스 루트에 남아있고, 이를 배제할
`.gitignore`나 다른 패키징 제외 규칙이 없다.

**위험도**: 이 정보 자체로 직접적인 시스템 접근권을 주진 않지만, 개발자 신원 확인이나
표적 피싱에 쓰일 수 있는 정찰 정보다. 익스플로잇 요건이 "소스 스냅샷을 읽을 수 있는
사람"뿐이라 발생 가능성 자체는 낮지 않지만, 영향도가 낮아 심각도는 Low로 유지했다.
**주의**: 대상이 Git 저장소가 아니라서 이 로그가 실제로 원격 저장소에 공개됐는지는 이
스캔만으로 확인 불가 — 확인되면 심각도를 올려야 한다.

**수정 방향**:
1. `dev-server.log`를 소스 배포본에서 제거하고, 이미 공유된 사본이 있다면 그것도 정리.
2. 루트에 `.gitignore` 추가: `*.log`, `node_modules/`, `.vite/`, `dist/`,
   `*.tsbuildinfo`, `.DS_Store`, `.env*` 제외하되 비밀 없는 `.env.example`만 예외로
   허용.
3. **이것만으로 키를 폐기·재발급할 필요는 없다** — 경로 노출이지 자격증명 노출이 아님.
   단, 나중에 실제 Git 저장소나 보관된 `.env` 파일에서 진짜 비밀이 발견되면 그때는
   폐기·재발급이 우선이다(원본 리포트 P0 항목과 이어지는 판단 기준).

---

### [3] 마이크 초기화 실패 시 스트림/AudioContext가 해제 안 될 수 있음

| Field | Value |
| --- | --- |
| Severity | Low |
| Confidence | Medium |
| CWE | CWE-772 (Missing Release of Resource after Effective Lifetime) |
| Affected lines | `src/pages/VoiceQuestionPage.tsx:292-322, 133-143, 373-378` |

**요약**: 마이크 권한을 얻은 뒤 `startRecording`이 여러 단계(AudioContext 생성/resume,
노드 생성/연결, MediaRecorder 생성)를 거치는데, 이 단계들이 각각 예외를 던질 수 있는데도
**`MediaStream`/`AudioContext`를 cleanup이 알고 있는 ref에 등록하는 건 그 이후**다. 그
사이에 예외가 나면 catch 핸들러가 `cleanupRecording`을 호출해도 ref에 없는 리소스는
정리 대상에서 빠진다.

```tsx
const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
// ↓ 이 사이에서 예외가 나면 stream/audioContext가 정리되지 않는다
const audioContext = new AudioContextConstructor()
if (audioContext.state === 'suspended') await audioContext.resume()
const source = audioContext.createMediaStreamSource(stream)
// ...
mediaStreamRef.current = stream       // ← 여기서야 비로소 정리 대상으로 등록됨
audioContextRef.current = audioContext
```

**위험도**: 마이크 하드웨어/오디오 리소스가 필요 이상으로 계속 켜져 있을 수 있다는
프라이버시·리소스 문제지만, 실제로 오디오가 어딘가로 전송된다는 증거는 없고 원격 공격
경로도 아니다. 발생 조건도 "초기화 도중 예외적 실패"라는 좁은 구간이라 발생 가능성도
낮음.

**수정 방향**:
1. `getUserMedia` 성공 직후 바로 stream을 ref에 등록하고, `AudioContext` 생성 직후
   바로 등록한다(등록을 뒤로 미루지 않는다).
2. 또는 로컬 변수 + `initializationCommitted` 플래그를 두고 `finally` 블록에서
   "설정이 완료되지 않았으면" 모든 트랙 정지·노드 연결 해제·컨텍스트 종료를 수행한다.
3. 각 `await` 지점 이후 generation/mount 상태를 재확인한다.

---

### [4] 오류 경로에서 전사문·세션 정보가 브라우저 콘솔에 남을 수 있음

| Field | Value |
| --- | --- |
| Severity | Low |
| Confidence | Medium |
| CWE | CWE-532 (Insertion of Sensitive Information into Log File) |
| Affected lines | `src/services/apiBase.ts:134-143`, `src/services/voiceApi.ts:71-76`, `src/pages/VoiceQuestionPage.tsx:247`, `src/App.tsx:272-278` |

**요약**: 비정상/오류 API 응답이 `ApiRequestError.details`에 원본 그대로 저장되고,
일부 호출부가 이 에러 객체나 `details`를 통째로 `console.error`에 넘긴다.

```tsx
// src/pages/VoiceQuestionPage.tsx:247 — 에러 전체(= details 포함)를 그대로 로깅
console.error('[Voice API] 음성 답변 처리 실패', error)

// src/App.tsx:272-278 — 백엔드가 준 원본 상세 정보를 그대로 로깅
console.error('[Recommendation API] 답변 누락', error.details)
```

STT 결과가 정상적으로 들어있지만 다른 필드 하나가 스키마와 안 맞아서 거부되는 경우처럼,
**전사문이나 sessionId가 포함된 응답 전체가 오류 처리 경로를 타고 콘솔에 남을 수 있다.**

**위험도**: 노출 조건이 "오류/스키마 불일치 응답에 민감 필드가 실제로 들어있을 것" +
"같은 브라우저의 개발자 콘솔 접근권"이라 두 조건이 겹쳐야 해서 발생 가능성은 낮다. 다만
콘솔 수집기(예: 운영 텔레메트리)가 나중에 붙으면 영향 범위가 커질 수 있다.

**수정 방향**:
1. 프로덕션 `Error` 객체에 원본 API payload를 그대로 붙이지 않는다. 제어 흐름에 필요한
   고정 필드만 파싱해서 담고, `sessionId`·사용자 텍스트는 마스킹한다.
2. 로그에는 안정적인 오류 종류/상태코드/상관관계ID 정도만 남긴다.
3. 개발자용 상세 payload가 꼭 필요하면 `import.meta.env.DEV`로 감싸 프로덕션 빌드에서
   제거되게 한다.
4. 테스트: 일부러 이상한 값(sentinel transcript/sessionId)이 든 오류 응답을 흘려보내
   콘솔 어디에도 그 값이 안 남는지 확인.

---

## 결론

원본 리포트가 찾아낸 **실제 코드 문제 자체는 타당**해요 — 특히 [1](세션이 다음 사용자에게
그대로 넘어가는 문제)은 공용 상담 단말 제품 특성상 우선 고쳐야 할 이슈고요. 문제는 리포트
"생성" 과정에서 병렬 스캔 결과를 제대로 합치지 못해서 **같은 이슈를 최대 5번까지
중복해서 부풀려놨다**는 거예요. 이대로 백엔드 멘토나 팀에 전달하면 "이슈가 10개나
있다"는 잘못된 인상을 주고, 실제 우선순위 판단(뭐부터 고칠지)도 흐려져요.

이미지로 주신 P0/P1/P2 표는 이 파일에 없는 내용(Git 위생, 추천 안전정보 유실, 취소
비멱등성, 테스트 부재)을 포함하고 있어서, 그 항목들은 **다른 소스 파일을 받아야 검증
가능**해요 — 있으면 공유해주세요.
