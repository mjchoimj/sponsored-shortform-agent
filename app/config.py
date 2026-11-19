"""프로젝트 설정 — 모델 이름과 경로를 한 곳에서 관리한다.

LLM 은 AWS Bedrock 을 쓴다. 접속 키와 모델 이름은 .env 에서 읽는다.
모델을 바꾸려면 .env 에 GEN_MODEL / GEN_MODEL_FALLBACKS / GRADER_MODEL 을 적으면 된다.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

# --- API 키 -----------------------------------------------------------------
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID", "")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY", "")
# Bedrock 호출 리전. .env 의 AWS_DEFAULT_REGION 과 상관없이 이 값을 쓴다.
AWS_REGION = os.getenv("BEDROCK_REGION", "us-east-1")
# 한도에 걸리면 같은 모델을 이 리전들로 차례로 다시 시도한다 (모델을 바꾸기 전에).
FALLBACK_REGIONS = [
    r.strip() for r in os.getenv("BEDROCK_FALLBACK_REGIONS", "us-west-2").split(",") if r.strip()
]
LANGSMITH_API_KEY = os.getenv("LANGSMITH_API_KEY", "")  # P1, 선택
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "")  # P2, 선택

# --- 모델 -------------------------------------------------------------------
# 생성 모델: Agent 와 기준선이 같은 모델을 쓴다 (service.md "평가").
GEN_MODEL = os.getenv("GEN_MODEL", "us.anthropic.claude-haiku-4-5-20251001-v1:0")
# 생성 모델이 실패(한도·장애)하면 차례로 시도할 대체 모델.
GEN_MODEL_FALLBACKS = [
    m.strip()
    for m in os.getenv("GEN_MODEL_FALLBACKS", "us.amazon.nova-2-lite-v1:0").split(",")
    if m.strip()
]
# 채점 모델: 한 단계 위, temperature 0. Agent(app/)는 이 값을 쓰지 않는다.
GRADER_MODEL = os.getenv("GRADER_MODEL", "us.anthropic.claude-sonnet-4-6")
GRADER_TEMPERATURE = 0
# 채점 모델이 한도에 걸리면 차례로 쓸 예비 채점 모델 (어떤 모델로 채점했는지 결과에 기록된다).
GRADER_MODEL_FALLBACKS = [
    m.strip()
    for m in os.getenv("GRADER_MODEL_FALLBACKS", "us.anthropic.claude-sonnet-4-5-20250929-v1:0").split(",")
    if m.strip()
]
# 임베딩: 계정에 Bedrock 임베딩 모델이 없어 Chroma 기본 로컬 임베딩을 쓴다 (키 불필요).

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


def require_aws_keys() -> None:
    """AWS 키가 없으면 쉬운 안내와 함께 멈춘다."""
    if not (AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY):
        raise SystemExit(
            "AWS 키가 없습니다. .env 파일에 AWS_ACCESS_KEY_ID 와 AWS_SECRET_ACCESS_KEY 를 넣어 주세요."
        )
