# 협찬 숏폼 기획 Agent

협찬을 받은 인플루언서가 **채널 프로필**과 **협찬 정보**를 넣으면, 60초 이하 숏폼(9:16)의 기획안·스토리보드·체크 리포트·업로드 패키지를 만들어 주는 AI Agent입니다.
**채널 톤 유지**, **광고주 포인트 반영**, **광고 규정 준수**를 같은 비중으로 지킵니다.

> AX 교육 미니프로젝트. 기획 원문은 [service.md](service.md), 작업 목록은 [TASKS.md](TASKS.md), 결정 기록은 [docs/decisions.md](docs/decisions.md)에 있습니다.

## 결과 요약

20세트 × (Agent, 기준선)으로 평가했습니다. 기준선은 **같은 생성 모델(Claude Haiku 4.5)에 같은 입력**을 주고, 프롬프트 한 번으로 같은 형식의 결과를 뽑게 한 것입니다. 그래서 두 쪽의 점수 차이는 Agent의 **구조**(사전 점검 · RAG · 계획 · 코드 보정 · 검증·수정 루프)에서 나온 것입니다.

| | Agent | 기준선 |
|---|---|---|
| **전체** | **0.946** | 0.784 |
| A 채널 톤 | 0.938 | 0.938 |
| B 포인트 반영 | 1.000 | 1.000 |
| C 규정·구성 | **0.950** | 0.660 |
| T1 함정 탐지 | **0.857** | 0.143 |

성공 기준(Agent ≥ 0.9이고 기준선보다 높음): **달성**.
채점은 한 단계 위 모델인 Claude Sonnet 4.6(temperature 0)으로 했습니다.

- 케이스별 점수와, 케이스마다 생성·채점에 쓴 모델: [docs/results/eval_summary.md](docs/results/eval_summary.md)
- 같은 제품 × 다른 채널 비교표(훅 · 첫 대사 · 제목): [docs/results/channel_compare.md](docs/results/channel_compare.md)
- 실행 결과 예시(자취 채널 × 보풀 제거기 30초, 최종 검토에서 수정 요청 1회 반영): [docs/sample_output/기획안.md](docs/sample_output/기획안.md) · [storyboard.json](docs/sample_output/storyboard.json) · [check_report.json](docs/sample_output/check_report.json)

## 어떻게 동작하나

```mermaid
flowchart LR
    A[채널 프로필<br/>+ 협찬 정보] --> B[사전 점검] --> C[RAG 검색] --> D[콘셉트 3안] --> E[씬 배분 계획] --> F[스토리보드 생성] --> G{자동 검증}
    G -- 실패 · 3회 미만 --> E
    G -- 통과 --> H[저장]
    B -. 확인 .-> U((사용자))
    D -. 선택 .-> U
    G -. 검토 .-> U
    U -. 수정 요청 .-> E
```

| 단계 | 하는 일 | 사용 기술 |
|---|---|---|
| 사전 점검 | 거절 카테고리 · 포인트 개수 초과 · 금지 표현은 코드로, 길이·비율 초과 · 모순 · 콘셉트 충돌은 AI로 찾고 조정안을 냅니다 | Pydantic 구조화 출력 |
| 사용자 확인 (3곳) | 사전 점검 조정안, 콘셉트 선택, **최종 검토**(스토리보드·업로드 패키지를 보고 승인 · 수정 요청 · 반려. 수정 요청은 글로 적으면 계획부터 다시 만들어 자동 검증 후 다시 보여 줌, 최대 3회) | LangGraph `interrupt` |
| RAG | 금지 표현 · 훅 노하우 · 톤 유지법 문서를 검색합니다. 검색어는 모델이 정합니다 | Chroma(로컬 임베딩) + 키워드 혼합 검색, Tool Calling, `create_agent` |
| 계획 · 생성 | 씬별 초·제품 노출을 계획하고, 코드가 첫 씬 3초 이하 · 노출 30% 이하 · 길이 합을 보정합니다 | |
| 자동 검증 | 말투 · 시그니처 · 포인트 · 광고 표시 · 금지 표현 · 노출 비율 · 첫 씬 · 길이를 **코드로** 판정하고, 실패하면 이유를 붙여 다시 만듭니다(최대 3회) | 광고 표시 · 금지 표현은 자체 **MCP 서버**(광고 규정 검사기) |
| 안전장치 | 일시 오류 재시도, 실행당 호출 횟수 상한, 금지 표현 가드 | 미들웨어 |
| 실행 기록 | LangSmith 키가 있으면 LangSmith로, 없으면 `logs/`에 로컬 기록 | Trace |

규정(금지 표현, 광고 표시, 길이별 포인트 수, 노출 비율)은 [knowledge/rules.json](knowledge/rules.json) 한 곳에 모여 있습니다.

## 설치

필요한 것: Python 3.11 이상, AWS Bedrock 접속 키

```bash
pip install -r requirements.txt
cp .env.example .env
```

`.env`를 열어 아래 값을 채웁니다.

```
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
BEDROCK_REGION=us-east-1
# 선택: LANGSMITH_API_KEY=...   (없으면 logs/ 폴더에 기록)
```

모델은 [app/config.py](app/config.py)에서 정합니다.
- 생성: Claude Haiku 4.5. 실패하면 Nova 2 Lite로 넘어갑니다.
- 채점: Claude Sonnet 4.6. 실패하면 Sonnet 4.5로 넘어갑니다.
- us-east-1이 한도에 걸리면 같은 모델을 us-west-2에서 호출합니다.

## 실행

```bash
# 기획 만들기 (질문에 직접 답하는 대화형)
python -m app.main examples/normal.json

# 질문에 자동으로 기본값을 답하며 끝까지 실행
python -m app.main examples/normal.json --auto

# 다른 예시: 포인트가 너무 많은 경우 / 거절되는 카테고리
python -m app.main examples/trap_overflow.json
python -m app.main examples/rejected.json
```

결과는 `outputs/{시각}_{제품명}/`에 저장됩니다.
- `기획안.md`: 기획안 요약 · 스토리보드 표 · 체크 리포트 · 업로드 패키지
- `storyboard.json`: 스타일 시트 · 씬별 데이터 · 영문 이미지 프롬프트
- `check_report.json`: 항목별 통과 여부와 근거

입력 파일 형식은 [examples/normal.json](examples/normal.json)을 참고하세요. 채널 프로필은 `eval/channels/CH1~CH4.json`에 있는 가상 채널 4개입니다.

## 평가

```bash
python -m eval.run_eval                  # 20세트 × (Agent, 기준선) 전체, 결과가 이미 있으면 건너뜀
python -m eval.run_eval --fresh          # 처음부터 새로
python -m eval.run_eval --cases N01,F04  # 일부만
python -m eval.compare                   # 같은 제품 × 다른 채널 비교표
```

결과는 `eval/results/`(`summary.md`, `summary.json`, `compare.md`)에 저장됩니다.
- 평가 케이스: [eval/cases/](eval/cases/). 일반 13건, 함정 7건(분량 초과 3 · 모순 2 · 콘셉트 충돌 2)입니다.
- 채점기: [eval/grader.py](eval/grader.py). AI 판정은 반드시 원고의 문장을 인용하게 하고, 그 인용이 원고에 실제로 있는지 코드로 확인합니다.
- Agent(`app/`)는 채점기와 채점 프롬프트를 쓰지 않습니다.

## 기타 명령어

```bash
python -m app.rag                          # RAG 색인 다시 만들기 (knowledge/docs 수정 후)
python -m mcp_server.server --selftest     # MCP 광고 규정 검사기 단독 확인
python -m unittest discover tests -v       # 테스트 (AI 호출 없음)
```

## 폴더 구조

| 폴더 | 내용 |
|---|---|
| `app/` | Agent: 그래프, 노드, 검사, 미들웨어, Trace |
| `mcp_server/` | 광고 규정 검사기 MCP 서버 (금지 표현 · 광고 표시) |
| `knowledge/` | RAG 문서(`docs/`)와 규정(`rules.json`) |
| `examples/` | 데모 입력 |
| `eval/` | 가상 채널, 평가 케이스, 기준선, 채점기, 실행기 |
| `tests/` | 단위 테스트 |
| `docs/` | 결정 기록, 평가 결과 사본 |

## 알려진 한계

- **제품 노출(C3)**: 화면 설명에 제품 이름 없이 사용 장면만 적힌 씬은 코드가 '제품이 보인다'고 잡지 못합니다. 그래서 채점 AI가 다시 확인하면 노출이 30%를 넘는 경우가 있습니다(6건).
- **채널색(A4)**: 일부 채널에서 '솔직한 단점 언급' 같은 대표 포맷 요소가 빠지는 경우가 있습니다(4건).
- 평가 채널과 케이스는 모두 가상입니다. 실존 인플루언서의 이름·계정·대본은 넣지 않았습니다.
