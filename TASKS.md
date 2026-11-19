# TASKS

[service.md](service.md)의 MVP 표(P0/P1/P2)를 작업 단위로 쪼갠 목록.

**사용 규칙**
1. 위에서부터 하나씩만 한다. 끝나면 `[ ]` → `[x]`.
2. 각 작업은 "완료 확인" 명령이 통과해야 끝난 것으로 본다.
3. P0가 제때 안 끝나면 콘셉트를 "3안 + 선택" → "1안 + 승인"으로 줄인다 (service.md "아직 안 정한 것"). 모자라면 P2 → P1 순으로 버리고 P0는 건드리지 않는다.

---

## 0. 준비

- [x] **T00 · 프로젝트 뼈대** (P0)
  - 만들 것: 폴더 `app/` `app/checks/` `mcp_server/` `knowledge/docs/` `examples/` `eval/channels/` `eval/cases/` `outputs/`, `requirements.txt`, `.env.example`, `app/config.py`(생성 모델·채점 모델 이름을 한 곳에서 지정)
  - 라이브러리는 CLAUDE.md 표에 있는 것만: langchain, langchain-aws, boto3, langgraph, langchain-chroma, chromadb, mcp, langchain-mcp-adapters, pydantic, python-dotenv
  - 완료 확인: `pip install -r requirements.txt` 성공, `python -c "import app.config"` 오류 없음

## 1. 데이터 (AI 초안, 사람 검토)

- [x] **T01 · 가상 채널 4개** (P0)
  - 만들 것: `eval/channels/CH1~CH4.json` — 자취 살림(반말) · 직장인 출근룩(존댓말) · 맞벌이 주부 살림(존댓말) · 잔소리 큰언니 뷰티(반말)
  - 항목: concept, speech_style, tone_keywords, signature_opening, signature_ending, representative_format, avoid
  - 완료 확인: 4개 파일 모두 `json.load` 성공

- [x] **T02 · 평가셋 20세트** (P0)
  - 만들 것: `eval/cases/*.json` — 일반 13(같은 제품 × 다른 채널 쌍 2쌍 이상) · 분량 초과 3(개수·길이·비율) · 모순 2 · 채널 콘셉트 충돌 2
  - 각 케이스: 채널 ID, 협찬 정보, HITL 자동 응답 3개, (함정이면) 기대 함정 유형
  - 완료 확인: 20개 파일, 유형별 개수가 위와 일치

- [x] **T03 · 규칙 파일** (P0)
  - 만들 것: `knowledge/rules.json` — 금지 표현, 허용 광고 표시(`[광고]`·`#광고`), 단독 사용 시 실패 표시(`sponsored`·`ad`·`#내돈내산`), 길이별 포인트 상한(15/30/45/60초 → 2/3/4/5), 제품 노출 상한 30%, 훅 ≤ 3초, 거절 카테고리
  - 완료 확인: `python -c "import json;json.load(open('knowledge/rules.json',encoding='utf-8'))"`

- [x] **T04 · RAG 문서 + 데모 입력** (P0)
  - 만들 것: `knowledge/docs/`(공정위 추천·보증 심사지침 요약, 숏폼 노하우), `examples/` 데모 입력 3종(`normal.json` 포함)
  - 완료 확인: 파일 존재, 예시 3종 `json.load` 성공

## 2. 그래프 + HITL + 생성

- [x] **T05 · 데이터 모델** (P0)
  - 만들 것: `app/schemas.py` — 채널 프로필, 협찬 정보, 사전 점검 결과, 콘셉트, 씬 배분 계획, 스토리보드(씬: 정수 초·대사·자막·`product_visible`·영문 이미지 프롬프트), 업로드 패키지
  - 완료 확인: `examples/normal.json`과 채널 1개를 모델로 읽어 오류 없음

- [x] **T06 · 사전 점검 노드 + HITL ①** (P0)
  - 카테고리 거절·포인트 개수 초과는 코드, 모순·콘셉트 충돌·과장·길이/비율 초과는 LLM 판단 → 제안을 `interrupt`로 사용자에게 묻기
  - 완료 확인: 함정 케이스 1개에서 맞는 유형이 잡힘, 거절 카테고리 입력은 중단됨

- [x] **T07 · RAG 검색 도구** (P0)
  - 만들 것: Chroma 인덱싱 스크립트(`chroma_db/`에 저장) + 검색 함수를 Tool Calling 도구로 노출
  - 완료 확인: "광고 표시 위치" 검색 시 심사지침 문단이 나옴

- [x] **T08 · 콘셉트 3안 노드 + HITL ②** (P0)
  - 1안 채널 대표 포맷, 2·3안은 훅 유형 변경, 모두 채널 말투 유지 → 사용자가 하나 선택
  - 완료 확인: 3안이 나오고 선택 결과가 상태에 저장됨

- [x] **T09 · 씬 배분 계획 → 스토리보드 생성** (P0)
  - 계획: 포인트별 씬·초, 시그니처 멘트 위치, 설명란으로 보낼 포인트
  - 생성: 스토리보드 + 업로드 패키지(제목·설명란·해시태그·광고 표시) + 영문 스타일 시트·이미지 프롬프트
  - 완료 확인: 출력이 T05 모델 검증 통과

- [x] **T10 · 그래프 연결 + 실행 진입점** (P0)
  - 만들 것: `app/graph.py`, `app/main.py`
  - 완료 확인: `python -m app.main examples/normal.json`이 끝까지 돈다 (검증은 아직 없음)

## 3. 검증 + 수정 루프 + MCP + 저장

- [x] **T11 · 코드 검증** (P0)
  - 만들 것: `app/checks/` — A1 말투 비율(어미 없는 문구는 중립·제외), A2 시그니처, A3 avoid, B1 포인트(설명란 포함), C1 광고 표시, C2 금지 표현, C3 노출 ≤ 30%, C4 첫 씬 제품 없음, C5 길이 합
  - 완료 확인: 일부러 틀린 스토리보드로 각 항목이 fail 나는 테스트 통과

- [ ] **T12 · 수정 루프 + HITL ③** (P0)
  - 실패 시 원고가 아니라 씬 배분 계획으로 돌아감, 최대 3회, 그래도 실패하면 미통과 표시 → 최종 승인 `interrupt`
  - 완료 확인: 검증 실패를 강제했을 때 3회 후 미통과 표시로 최종 승인 단계에 도달

- [ ] **T13 · MCP 광고 규정 검사기** (P0)
  - 만들 것: `mcp_server/` FastMCP 서버(금지 표현 검사 도구 1개, `rules.json` 사용) + `langchain-mcp-adapters`로 Agent 실행 시 stdio 자동 기동
  - 완료 확인: MCP 서버 단독 실행 성공, Agent 실행 로그에 MCP 도구 호출이 보임

- [ ] **T14 · 저장** (P0)
  - 만들 것: `outputs/{시각}_{제품명}/기획안.md`, `storyboard.json`, `check_report.json`
  - 완료 확인: `examples/normal.json` 실행 후 세 파일 생성

## 4. 평가 → **MVP 완료**

- [ ] **T15 · 기준선** (P0)
  - 같은 생성 모델 + 같은 채널 프로필·협찬 정보, 프롬프트 1회로 같은 JSON 출력
  - 완료 확인: 케이스 1개로 기준선 JSON 생성

- [ ] **T16 · 채점기** (P0)
  - 만들 것: `eval/grader.py` — 코드 항목 + 채점 모델(상위 모델, temperature 0)로 A2 의미 판정·A4·B1·C3 재확인·T1. 근거 문장 인용을 받아 원고에 실제로 있는지 코드로 확인
  - Agent 코드(`app/`)는 이 파일·채점 프롬프트를 import 하지 않는다
  - 완료 확인: 결과 1건 채점 시 항목별 pass/fail + 근거 출력

- [ ] **T17 · 평가 실행 (1차)** (P0)
  - 만들 것: `eval/run_eval.py` — 20세트 × (Agent, 기준선), HITL 자동 응답, 전체·A·B·C·T1 점수표
  - 완료 확인: `python -m eval.run_eval` 이 점수표를 출력

## 5. P1

- [ ] **T18 · 미들웨어 3종** (P1) — 재시도, 호출 횟수 상한, 금지 표현 가드
- [ ] **T19 · LangSmith Trace** (P1) — 키 없으면 로컬 로그
- [ ] **T20 · MCP에 광고 표시 검사 추가** (P1)

## 6. 측정·문서

- [ ] **T21 · 평가 최종 실행** — 결과표 + "같은 제품 × 다른 채널" 비교표(훅·첫 대사·제목)
- [ ] **T22 · README + 명령어 정리** — 평가자용 README(실행 방법·결과표), CLAUDE.md "명령어" 칸 채우기

## 7. P2 — P0·P1이 끝난 뒤에만

- [ ] **T23 · Tavily 웹 리서치 + 캐시** (P2)
- [ ] **T24 · 대화형 입력** (P2)
- [ ] **T25 · 노하우 문서 확장** (P2)
- [ ] **T26 · LangSmith 공유 링크 + 스크린샷** (P2)

## 8. 제출

- [ ] **T27 · 제출**
  - `git status`로 `.env`·API 키가 올라가지 않는지 확인 → GitHub push + ZIP
