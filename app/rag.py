"""RAG — knowledge/docs 를 Chroma(chroma_db/)에 넣고, 검색을 Tool Calling 도구로 노출한다.

임베딩은 Chroma 기본 로컬 임베딩(키 불필요). 인덱스 만들기:
    python -m app.rag
"""

from __future__ import annotations

import re
import sys
import threading
from functools import lru_cache

from chromadb.utils.embedding_functions import DefaultEmbeddingFunction
from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_core.tools import tool

from app import config

COLLECTION = "knowledge"


class LocalEmbeddings(Embeddings):
    """Chroma 기본 임베딩을 LangChain Embeddings 모양으로 감싼다."""

    def __init__(self) -> None:
        self._fn = DefaultEmbeddingFunction()

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [list(map(float, v)) for v in self._fn(texts)]

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]


def split_markdown(name: str, text: str) -> list[Document]:
    """문서를 '## 소제목' 단위로 자른다. 소제목 앞 머리말은 첫 조각에 붙인다."""
    title = next((l[2:].strip() for l in text.splitlines() if l.startswith("# ")), name)
    parts = re.split(r"(?m)^## ", text)
    intro, sections = parts[0].strip(), [p.strip() for p in parts[1:] if p.strip()]
    if not sections:
        sections, intro = [intro], ""
    docs = []
    for i, part in enumerate(sections):
        heading = part.splitlines()[0].strip()
        body = ("## " + part) if parts[1:] else part
        if i == 0 and intro:
            body = intro + "\n\n" + body
        docs.append(
            Document(
                page_content=f"[{title} > {heading}]\n{body}",
                metadata={"source": name, "title": title, "heading": heading},
            )
        )
    return docs


def load_docs() -> list[Document]:
    docs = []
    for path in sorted(config.DOCS_DIR.glob("*.md")):
        docs.extend(split_markdown(path.name, path.read_text(encoding="utf-8")))
    return docs


@lru_cache(maxsize=1)
def get_store() -> Chroma:
    return Chroma(
        collection_name=COLLECTION,
        embedding_function=LocalEmbeddings(),
        persist_directory=str(config.CHROMA_DIR),
    )


def build_index() -> int:
    """인덱스를 처음부터 다시 만든다. 넣은 조각 수를 돌려준다."""
    store = get_store()
    store.reset_collection()
    docs = load_docs()
    store.add_documents(docs, ids=[f"{d.metadata['source']}#{i}" for i, d in enumerate(docs)])
    return len(docs)


def _bigrams(text: str) -> set[str]:
    s = re.sub(r"[^0-9a-zA-Z가-힣]", "", text.lower())
    return {s[i : i + 2] for i in range(len(s) - 1)}


def _keyword_score(query: str, doc: Document) -> float:
    q = _bigrams(query)
    return len(q & _bigrams(doc.page_content)) / len(q) if q else 0.0


# 검색 에이전트가 도구를 동시에 여러 번 부르면 Chroma 연결이 겹쳐 실패한다 → 한 번에 하나씩.
_LOCK = threading.Lock()


def search(query: str, k: int = 3) -> list[Document]:
    with _LOCK:
        return _search(query, k)


def _search(query: str, k: int = 3) -> list[Document]:
    """벡터 순위 + 키워드(두 글자 단위) 순위를 합쳐(RRF) 상위 k개를 돌려준다.

    로컬 임베딩이 한국어에 약해서, 키워드 일치로 보완한다.
    """
    store = get_store()
    if not store.get(limit=1)["ids"]:  # 인덱스가 비어 있으면 자동으로 만든다
        build_index()
    everything = store.get()
    docs = [Document(page_content=c, metadata=m) for c, m in zip(everything["documents"], everything["metadatas"])]
    key = lambda d: (d.metadata["source"], d.metadata["heading"])

    vec_rank = {key(d): r for r, d in enumerate(store.similarity_search(query, k=len(docs)))}
    kw_sorted = sorted(docs, key=lambda d: _keyword_score(query, d), reverse=True)
    kw_rank = {key(d): r for r, d in enumerate(kw_sorted)}

    def rrf(d: Document) -> float:
        return 1 / (60 + vec_rank.get(key(d), len(docs))) + 1 / (60 + kw_rank[key(d)])

    return sorted(docs, key=rrf, reverse=True)[:k]


@tool
def search_knowledge(query: str) -> str:
    """광고 규정(공정위 추천·보증 심사지침, 카테고리별 금지 표현)과 숏폼 기획 노하우(훅, 길이별 구성,
    채널 톤 유지, 광고주 요구 조율) 문서에서 query 와 관련된 문단을 찾아 돌려준다."""
    hits = search(query, k=3)
    return "\n\n---\n\n".join(d.page_content for d in hits) or "(관련 문서 없음)"


if __name__ == "__main__":
    n = build_index()
    print(f"인덱스 완료: 조각 {n}개 → {config.CHROMA_DIR}")
    if len(sys.argv) > 1:
        print(search_knowledge.invoke(" ".join(sys.argv[1:])))
