# rag.py
import os
from dotenv import load_dotenv

load_dotenv()

EMBEDDING_MODEL = "text-embedding-3-small"
COLLECTION_NAME = "langchain"

_db = None


def _get_db():
    global _db
    if _db is None:
        from langchain_openai import OpenAIEmbeddings
        from langchain_qdrant import QdrantVectorStore
        from qdrant_client import QdrantClient

        url = os.getenv("QDRANT_URL", "").replace("https://", "")
        key = os.getenv("QDRANT_API_KEY", "")
        if not url or not key:
            raise RuntimeError("QDRANT_URL ou QDRANT_API_KEY não definidos.")

        client = QdrantClient(host=url, port=443, https=True, api_key=key, timeout=30)
        _db = QdrantVectorStore(
            client=client,
            collection_name=COLLECTION_NAME,
            embedding=OpenAIEmbeddings(model=EMBEDDING_MODEL),
            content_payload_key="page_content",
            metadata_payload_key="metadata",
        )
    return _db


def buscar_trechos(query: str, categoria: str | None = None, k: int = 5) -> list[dict]:
    """Retorna trechos relevantes do Qdrant com metadados estruturados."""
    if k <= 0:
        return []

    db = _get_db()

    if categoria:
        from qdrant_client.models import Filter, FieldCondition, MatchValue
        search_filter = Filter(
            must=[FieldCondition(key="categoria", match=MatchValue(value=categoria))]
        )
        docs = db.similarity_search(query, k=k, filter=search_filter)
    else:
        docs = db.similarity_search(query, k=k)

    return [
        {
            "fonte":     doc.metadata.get("fonte", "desconhecido"),
            "pagina":    doc.metadata.get("pagina", "?"),
            "categoria": doc.metadata.get("categoria", categoria or "desconhecida"),
            "trecho":    doc.page_content.strip(),
        }
        for doc in docs
    ]


def buscar_contexto(query: str, categoria: str, k: int = 5) -> str:
    """Retorna trechos relevantes dos livros como string formatada."""
    trechos_estruturados = buscar_trechos(query, categoria=categoria, k=k)
    if not trechos_estruturados:
        print(f"\n📚 RAG [{categoria.upper()}] — nenhum trecho encontrado para: {query[:280]!r}")
        return ""

    separador = "─" * 72
    print(f"\n{'═' * 72}")
    print(f"📚 RAG [{categoria.upper()}]  query: {query[:80]!r}")
    print(f"{'═' * 72}")

    trechos = []
    for i, item in enumerate(trechos_estruturados, 1):
        fonte  = item["fonte"]
        pagina = item["pagina"]
        trecho = item["trecho"]
        print(f"\n  [{i}] {fonte}  —  p. {pagina}")
        print(f"  {separador}")
        preview = trecho[:300] + ("…" if len(trecho) > 300 else "")
        for linha in preview.splitlines():
            print(f"      {linha}")
        trechos.append(f"[{fonte}, p.{pagina}]\n{trecho}")

    print(f"\n{'═' * 72}\n")
    return "\n\n---\n\n".join(trechos)
