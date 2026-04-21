# popular_db.py
# Lê os JSONs de backup_textos/, limpa os chunks e popula o ChromaDB.
#
# Execução:
#   .venv/bin/python popular_db.py
#
# Para limpar o banco antes de re-indexar:
#   .venv/bin/python popular_db.py --reset

import re
import os
import sys
import json
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
import tiktoken
from langchain_openai import OpenAIEmbeddings
from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

load_dotenv()

BACKUP_DIR       = "./backup_textos"
DB_DIR           = "./db_knowledge"
COST_REPORT_PATH = "./embedding_cost_report.json"

EMBEDDING_MODEL    = "text-embedding-3-small"
PRECO_POR_M_TOKENS = 0.02   # USD por 1M tokens

embeddings = OpenAIEmbeddings(model=EMBEDDING_MODEL)
encoder    = tiktoken.encoding_for_model(EMBEDDING_MODEL)


# ── Limpeza de artefatos ───────────────────────────────────────────────────────
# Aplicada sobre cada página ANTES do split, para não contaminar os chunks.

_ARTEFATOS = [
    r"(?im)^\s*\*{0,2}Identificação do Idioma[:\*]*.*$",
    r"(?im)^\s*\*{0,2}O idioma d[ae]sta página é[^\.]*\.\s*$",
    r"(?im)^\s*\*{0,2}Transcrição Fiel do Texto[:\*]*.*$",
    r"(?im)^\s*\*{0,2}Descrição Detalhada dos Diagramas[:/\*]*.*$",
    r"(?im)^\s*\*{0,2}Símbolo[s]?[:\*].*$",
    r"(?im)^\s*\*{0,2}Notas Adicionais[:\*].*$",
    r"(?m)^\s*\d{1,4}\s*$",           # número de página isolado
]


def limpar_texto(texto: str) -> str:
    """Remove artefatos OCR/Gemini do texto de uma página."""
    for padrao in _ARTEFATOS:
        texto = re.sub(padrao, "", texto)
    texto = re.sub(r" {2,}", " ", texto)
    texto = re.sub(r"\n{3,}", "\n\n", texto)
    return texto.strip()


# ── Filtro de qualidade de chunk ───────────────────────────────────────────────

# Padrões que identificam páginas/chunks de pouco valor semântico
_PAGINAS_DESCARTAVEIS = re.compile(
    r"(?i)^\s*("
    r"referências|references|bibliography|bibliograph|índice|index|"
    r"sumário|contents|agradecimentos|acknowledgements|"
    r"lista de figuras|list of figures|"
    r"sobre o autor|about the author"
    r")",
    re.MULTILINE,
)

_CHUNK_MIN_CHARS    = 150   # chunks menores que isso são descartados
_CHUNK_MIN_PALAVRAS = 20    # chunks com menos palavras são descartados
_CHUNK_MAX_FRAC_NUM = 0.30  # se >30% dos chars são dígitos/pontuação → descarta


def chunk_valido(texto: str) -> tuple[bool, str]:
    """
    Retorna (True, "") se o chunk tem conteúdo útil,
    ou (False, motivo) caso contrário.
    """
    t = texto.strip()

    if len(t) < _CHUNK_MIN_CHARS:
        return False, f"muito curto ({len(t)} chars)"

    palavras = t.split()
    if len(palavras) < _CHUNK_MIN_PALAVRAS:
        return False, f"poucas palavras ({len(palavras)})"

    # Proporção de caracteres numéricos + pontuação simples
    nao_alfa = sum(1 for c in t if not c.isalpha() and c not in " \n")
    if nao_alfa / len(t) > _CHUNK_MAX_FRAC_NUM:
        return False, f"muito numérico/simbólico ({nao_alfa/len(t):.0%})"

    if _PAGINAS_DESCARTAVEIS.search(t[:200]):
        return False, "página de referências/índice"

    return True, ""


# ── Helpers ────────────────────────────────────────────────────────────────────

def contar_tokens(texto: str) -> int:
    return len(encoder.encode(texto))


# ── Pipeline principal ─────────────────────────────────────────────────────────

def _fontes_ja_indexadas() -> set[str]:
    """
    Consulta o ChromaDB existente e devolve o conjunto de valores
    únicos do campo 'fonte' já presentes — sem gerar embeddings.
    Retorna conjunto vazio se o banco não existir.
    """
    if not Path(DB_DIR).exists():
        return set()
    try:
        db = Chroma(persist_directory=DB_DIR, embedding_function=embeddings)
        total = db._collection.count()
        if total == 0:
            return set()
        # get() sem where retorna todos — lemos em lotes para evitar timeout
        fontes: set[str] = set()
        limite = 5000
        offset = 0
        while True:
            lote = db._collection.get(
                limit=limite,
                offset=offset,
                include=["metadatas"],
            )
            for m in lote["metadatas"]:
                if m and "fonte" in m:
                    fontes.add(m["fonte"])
            if len(lote["ids"]) < limite:
                break
            offset += limite
        return fontes
    except Exception as e:
        print(f"⚠️  Não foi possível ler fontes existentes ({e}). Modo incremental desativado.")
        return set()


def popular_banco(reset: bool = False, incremental: bool = True):
    """
    Indexa backup_textos/ no ChromaDB.

    reset=True      → apaga o banco e recria do zero (re-gera todos os embeddings)
    incremental=True → padrão: pula livros cujo 'fonte' já existe no banco
    """
    if reset:
        import shutil
        if Path(DB_DIR).exists():
            shutil.rmtree(DB_DIR)
            print(f"🗑️  Banco anterior removido: {DB_DIR}")
        fontes_existentes: set[str] = set()
    elif incremental:
        fontes_existentes = _fontes_ja_indexadas()
        if fontes_existentes:
            print(f"🔍 Modo incremental: {len(fontes_existentes)} fonte(s) já indexada(s) — serão puladas.")
    else:
        fontes_existentes = set()

    documentos_para_db = []
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=1000,
        chunk_overlap=150,
        separators=["\n\n", "\n", ". ", " ", ""],
    )

    json_files = sorted(Path(BACKUP_DIR).rglob("*.json"))
    if not json_files:
        print("⚠️  Nenhum arquivo JSON encontrado em backup_textos/")
        return

    total_tokens        = 0
    total_descartados   = 0
    detalhes_por_livro  = []

    for arquivo_json in json_files:
        categoria = arquivo_json.parent.name
        fonte_key = arquivo_json.stem

        if fonte_key in fontes_existentes:
            print(f"\n⏩ [{categoria}] {fonte_key}  (já indexado)")
            continue

        print(f"\n📦 [{categoria}] {fonte_key}")

        with open(arquivo_json, encoding="utf-8") as f:
            paginas = json.load(f)

        tokens_livro    = 0
        chunks_livro    = 0
        descartados_livro = 0

        for p in paginas:
            texto_bruto = p.get("texto", "").strip()
            if not texto_bruto:
                continue

            # 1. Limpar artefatos da página inteira
            texto = limpar_texto(texto_bruto)
            if not texto:
                continue

            # 2. Dividir em chunks
            chunks = splitter.split_text(texto)

            for pedaco in chunks:
                valido, motivo = chunk_valido(pedaco)
                if not valido:
                    descartados_livro += 1
                    continue

                tokens_chunk = contar_tokens(pedaco)
                tokens_livro += tokens_chunk
                chunks_livro += 1

                doc = Document(
                    page_content=pedaco,
                    metadata={
                        "fonte":     fonte_key,
                        "categoria": categoria,
                        "pagina":    p["pagina"],
                    },
                )
                documentos_para_db.append(doc)

        total_tokens      += tokens_livro
        total_descartados += descartados_livro
        custo_livro        = (tokens_livro / 1_000_000) * PRECO_POR_M_TOKENS

        detalhes_por_livro.append({
            "livro":          fonte_key,
            "categoria":      categoria,
            "chunks_uteis":   chunks_livro,
            "chunks_descartados": descartados_livro,
            "tokens":         tokens_livro,
            "custo_usd":      round(custo_livro, 6),
        })

        print(
            f"   chunks úteis: {chunks_livro}  |  descartados: {descartados_livro}"
            f"  |  tokens: {tokens_livro:,}  |  custo: ${custo_livro:.4f}"
        )

    if not documentos_para_db:
        print("\n✅ Nenhum livro novo para indexar. Banco já está atualizado.")
        return

    custo_total = (total_tokens / 1_000_000) * PRECO_POR_M_TOKENS

    print(f"\n✨ Indexando {len(documentos_para_db)} chunks novos no ChromaDB...")

    LOTE = 500   # ChromaDB Rust trava com lotes muito grandes

    if Path(DB_DIR).exists() and not reset:
        # Banco já existe: adiciona em lotes pequenos
        db = Chroma(persist_directory=DB_DIR, embedding_function=embeddings)
        for inicio in range(0, len(documentos_para_db), LOTE):
            lote = documentos_para_db[inicio: inicio + LOTE]
            db.add_documents(lote)
            print(f"   lote {inicio // LOTE + 1}/{-(-len(documentos_para_db) // LOTE)}: {len(lote)} chunks adicionados")
    else:
        # Banco novo ou reset: from_documents já faz o batching internamente
        Chroma.from_documents(
            documents=documentos_para_db,
            embedding=embeddings,
            persist_directory=DB_DIR,
        )
    print("✅ Banco de dados vetorial atualizado com sucesso!")

    # ── Relatório de custo ────────────────────────────────────────────────────
    relatorio = {
        "modelo":               EMBEDDING_MODEL,
        "preco_por_m_tokens":   PRECO_POR_M_TOKENS,
        "data":                 datetime.now().isoformat(timespec="seconds"),
        "total_tokens":         total_tokens,
        "total_chunks_uteis":   len(documentos_para_db),
        "total_chunks_descartados": total_descartados,
        "custo_total_usd":      round(custo_total, 6),
        "livros":               detalhes_por_livro,
    }

    with open(COST_REPORT_PATH, "w", encoding="utf-8") as f:
        json.dump(relatorio, f, ensure_ascii=False, indent=2)

    print(f"\n📊 Relatório salvo em {COST_REPORT_PATH}")
    print(f"   Chunks novos     : {len(documentos_para_db):,}")
    print(f"   Chunks descartados: {total_descartados:,}")
    print(f"   Total tokens     : {total_tokens:,}")
    print(f"   Custo total      : ${custo_total:.4f} USD")


if __name__ == "__main__":
    reset       = "--reset"       in sys.argv
    sem_incr    = "--sem-incremental" in sys.argv
    if reset:
        print("⚠️  Modo --reset: o banco atual será apagado e recriado do zero.")
    popular_banco(reset=reset, incremental=not sem_incr)
