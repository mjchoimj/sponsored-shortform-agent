"""프로젝트 설정 — 모델 이름과 경로를 한 곳에서 관리한다.

API 키와 모델 이름은 .env 에서 읽는다. 모델을 바꾸려면 .env 에
GEN_MODEL / GRADER_MODEL / EMBEDDING_MODEL 을 적으면 된다.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

# --- API 키 -----------------------------------------------------------------
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
LANGSMITH_API_KEY = os.getenv("LANGSMITH_API_KEY", "")  # P1, 선택
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "")  # P2, 선택

# --- 모델 -------------------------------------------------------------------
# 생성 모델: Agent 와 기준선이 같은 모델을 쓴다 (service.md "평가").
GEN_MODEL = os.getenv("GEN_MODEL", "gpt-4.1-mini")
# 생성 모델이 실패(한도·장애)하면 차례로 시도할 대체 모델.
GEN_MODEL_FALLBACKS = [
    m.strip()
    for m in os.getenv("GEN_MODEL_FALLBACKS", "gpt-4o-mini").split(",")
    if m.strip()
]
# 채점 모델: 한 단계 위, temperature 0. Agent(app/)는 이 값을 쓰지 않는다.
GRADER_MODEL = os.getenv("GRADER_MODEL", "gpt-4.1")
GRADER_TEMPERATURE = 0
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")

# --- 경로 -------------------------------------------------------------------
KNOWLEDGE_DIR = ROOT / "knowledge"
RULES_PATH = KNOWLEDGE_DIR / "rules.json"
DOCS_DIR = KNOWLEDGE_DIR / "docs"
CHROMA_DIR = ROOT / "chroma_db"
EXAMPLES_DIR = ROOT / "examples"
EVAL_DIR = ROOT / "eval"
OUTPUTS_DIR = ROOT / "outputs"

# --- 수정 루프 ---------------------------------------------------------------
MAX_REVISIONS = 3


def require_openai_key() -> None:
    """OpenAI 키가 없으면 쉬운 안내와 함께 멈춘다."""
    if not OPENAI_API_KEY:
        raise SystemExit(
            "OPENAI_API_KEY 가 없습니다. .env 파일에 OPENAI_API_KEY=sk-... 를 추가해 주세요."
        )
