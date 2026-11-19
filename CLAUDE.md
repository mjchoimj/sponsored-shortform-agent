# CLAUDE.md

협찬 숏폼 기획 Agent — AX 교육 미니프로젝트. 기획 원문은 [service.md](service.md)이며, 모든 결정은 그 문서를 따른다.

## 프로젝트 한 줄
협찬 받은 인플루언서가 제품과 광고주 홍보 포인트를 넣으면, 채널 톤을 지키면서 광고 규정을 준수하는 60초 이하 숏폼 기획안·스토리보드·체크 리포트·업로드 패키지를 만드는 AI Agent.

## 기술 스택
| 영역 | 사용 기술 |
|---|---|
| 언어 | Python 3.11+, 설치는 `pip install -r requirements.txt` |
| LLM | AWS Bedrock (`langchain-aws`, `boto3`, 리전 us-east-1, `us.` 모델). 생성 Claude Haiku 4.5(예비 Nova 2 Lite), 채점 Claude Sonnet 4.6. 모델은 `app/config.py` 한 곳에서 지정 |
| Agent 프레임워크 | LangChain, LangGraph (상태 그래프, 수정 루프, `interrupt` 기반 HITL) |
| RAG | 로컬 벡터 DB **Chroma** (`langchain-chroma`, `chroma_db/`에 저장) + Chroma 기본 로컬 임베딩(키 불필요), 검색은 Tool Calling 도구로 노출 |
| MCP | Python MCP SDK(FastMCP)로 만든 자체 "광고 규정 검사기" 서버, `langchain-mcp-adapters`로 연결 (stdio, Agent 실행 시 자동 기동) |
| Middleware | LangChain middleware: 재시도, 호출 횟수 제한, 금지 표현 가드 (P1) |
| 구조화 출력 | Pydantic 모델 |
| Trace | LangSmith (키 없으면 로컬 로그) (P1) |
| 웹 검색 | Tavily + 캐시 (P2) |
| 설정 | `python-dotenv`, `.env` (`AWS_ACCESS_KEY_ID`·`AWS_SECRET_ACCESS_KEY`·`BEDROCK_REGION`(기본 us-east-1), `LANGSMITH_API_KEY`·`TAVILY_API_KEY` 선택) |
필요 시 모델은 조정해서 사용하거나 복수의 모델을 상황에 맞춰 변경하여 중단없이 쓸 수 있게 한다.

## 작업 규칙
- **사용자는 개발자가 아니다.** 설명은 쉬운 한국어로 하고, 명령어는 그대로 복사해 실행할 수 있게 준다.
- **MVP 우선순위를 지킨다** (service.md 2.2장). P0를 끝내기 전에 P1·P2 기능을 만들지 않는다.
- **검증은 코드로 결정론적으로.** 금지 표현·광고 표시·길이·비율은 `knowledge/rules.json`과 코드로 판정한다. 채점 AI를 쓰는 항목은 근거 문장 인용을 받아 코드로 존재 여부를 확인한다.
- **Agent 내부 검사와 최종 채점을 분리한다** (service.md 8.0). Agent는 채점 모델·채점 프롬프트를 호출하지 않는다.
- 산출물 언어: 기획안·대사·자막·업로드 패키지는 한국어, 스타일 시트·이미지 프롬프트는 영어.
- **비밀 정보 금지**: `.env`와 API 키는 절대 커밋하지 않는다. `.env.example`만 올린다. Public 저장소다.
- 실존 인플루언서의 실명·계정·대본 원문을 저장소에 넣지 않는다. 평가용 채널은 가상 프로필(`eval/channels/CH1~CH4`)만 쓴다.
- 괜찮은 레퍼런스 코드를 깃허브에서 찾아서 레퍼런스로 삼거나 (있을 경우) 현재 ref 폴더 내 코드를 참조한다. 절대 사용자의 허락없이 신규 프레임워크 또는 라이브러리를 들이지 않는다.
- 한 번에 TASKS.md의 작업 하나만 한다.

- 계산, 규칙 판정은 LLM이 아니라 파이썬 코드로 하는 원칙으로 진행한다. 필요시 LLM 판정부분을 덧붙여 추가한다.

- API 키는 .env에서 읽는다.

## 폴더 구조 (예정)
`app/`(Agent) · `mcp_server/`(규정 검사기) · `knowledge/`(RAG 문서, `rules.json`) · `examples/`(데모 입력) · `eval/`(평가셋, 기준선, 채점) · `outputs/`(실행 결과). 상세는 service.md 11장.

## 명령어
구현 후 채운다. (실행, 평가 실행, MCP 서버 단독 실행)
