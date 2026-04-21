"""
catalogo_livros.py
Mapeamento das fontes bibliográficas presentes no banco RAG
para citações formatadas profissionalmente.

A chave de cada entrada é o valor exato do campo "fonte" no ChromaDB
(definido em popular_db.py como arquivo_json.stem — nome do arquivo sem extensão).
"""

from __future__ import annotations

# ── Catálogo principal ─────────────────────────────────────────────────────────

CATALOGO: dict[str, dict] = {

    
}


# ── Catálogo gerado automaticamente (gerar_catalogo.py) ───────────────────────
# Carregado em tempo de importação; CATALOGO manual tem prioridade.

import json as _json
from pathlib import Path as _Path

_CATALOGO_GERADO_PATH = _Path().resolve() / "catalogo_gerado.json"

def _carregar_gerado() -> dict:
    if _CATALOGO_GERADO_PATH.exists():
        try:
            return _json.loads(_CATALOGO_GERADO_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}

_CATALOGO_GERADO: dict = _carregar_gerado()


def _resolver(fonte_key: str) -> dict | None:
    """Retorna info do livro: manual tem prioridade sobre gerado."""
    return CATALOGO.get(fonte_key) or _CATALOGO_GERADO.get(fonte_key)


# ── Função de formatação ───────────────────────────────────────────────────────

def formatar_fonte(fonte_key: str, paginas: list[str]) -> str:
    """
    Recebe a chave de fonte (campo 'fonte' do ChromaDB) e a lista de páginas
    consultadas, e devolve uma citação bibliográfica formatada.

    Exemplos de saída:
        *Saturn: A New Look at an Old Devil* — Liz Greene (p. 42)
        *Planets in Transit* — Robert Hand (pp. 15, 88, 203)
        *Jung e o Tarô* — Sallie Nichols (p. 7)
    """
    pag_str = f"pp. {', '.join(paginas)}" if len(paginas) > 1 else f"p. {paginas[0]}"

    info = _resolver(fonte_key)

    if info:
        titulo = info["titulo"]
        autor  = info.get("autor", "")
        ano    = info.get("ano", "")
        autor_parte = f" — {autor}" if autor else ""
        ano_parte   = f", {ano}"    if ano    else ""
        return f"*{titulo}*{autor_parte}{ano_parte} ({pag_str})"

    # ── Fallback para fontes ainda não catalogadas ─────────────────────────────
    # Tenta separar por " - " (padrão "Titulo - Autor" dos PDFs com nome limpo)
    if " - " in fonte_key:
        partes = fonte_key.split(" - ", 1)
        titulo = partes[0].strip()
        autor  = partes[1].strip()
        return f"*{titulo}* — {autor} ({pag_str})"

    # Último recurso: limpa o slug e exibe sem autor
    titulo = (
        fonte_key
        .replace("_", " ")
        .replace("-", " ")
        .strip()
        .title()
    )
    return f"*{titulo}* ({pag_str})"

def formatar_fonte_abnt(fonte_key: str, paginas: list[str]) -> str:
    """
    Formata a referência bibliográfica seguindo a norma ABNT NBR 6023.
    Padrao: SOBRENOME, Nome. Titulo. Ano. (p. X).
    """
    info = _resolver(fonte_key)
    pag_str = f"p. {', '.join(paginas)}" if len(paginas) > 1 else f"p. {paginas[0]}"

    if info:
        titulo = info["titulo"]
        autor_raw = info.get("autor", "")
        ano = info.get("ano", "s.d.") # s.d. = sem data
        
        # Inversão de nome para padrão ABNT (ex: Carl Jung -> JUNG, Carl)
        if autor_raw and " " in autor_raw:
            partes = autor_raw.split()
            sobrenome = partes[-1].upper()
            nome = " ".join(partes[:-1])
            autor_abnt = f"{sobrenome}, {nome}"
        else:
            autor_abnt = autor_raw.upper() if autor_raw else "AUTOR DESCONHECIDO"

        return f"{autor_abnt}. **{titulo}**. {ano}. ({pag_str})."

    # Fallback para chaves não encontradas no catálogo
    titulo_limpo = fonte_key.replace("_", " ").replace("-", " ").title()
    return f"**{titulo_limpo}**. ({pag_str})."


def fontes_para_markdown(rag_ctx: str) -> str:
    """
    Extrai todas as referências de um texto RAG e devolve um bloco Markdown
    com citações bibliográficas formatadas profissionalmente.

    O texto RAG contém padrões como:
        [nome-do-livro, p.42]
        [Autor - Título, p.7]

    Retorna string vazia se não houver fontes identificáveis.
    """
    import re
    from collections import OrderedDict

    paginas_por_fonte: dict[str, list[str]] = OrderedDict()

    for m in re.finditer(r"\[([^\]]+),\s*p\.(\d+)\]", rag_ctx):
        chave = m.group(1).strip()
        pag   = m.group(2).strip()
        if chave not in paginas_por_fonte:
            paginas_por_fonte[chave] = []
        if pag not in paginas_por_fonte[chave]:
            paginas_por_fonte[chave].append(pag)

    if not paginas_por_fonte:
        return ""

    linhas = [
        f"- {formatar_fonte(fonte, pags)}"
        for fonte, pags in paginas_por_fonte.items()
    ]

    return "\n\n---\n**Referências bibliográficas**\n" + "\n".join(linhas)

def fontes_para_markdown_abnt(rag_ctx: str) -> str:
    """
    Extrai todas as referências de um texto RAG e devolve um bloco Markdown
    com citações bibliográficas formatadas profissionalmente.

    O texto RAG contém padrões como:
        [nome-do-livro, p.42]
        [Autor - Título, p.7]

    Retorna string vazia se não houver fontes identificáveis.
    """
    import re
    from collections import OrderedDict

    paginas_por_fonte: dict[str, list[str]] = OrderedDict()

    for m in re.finditer(r"\[([^\]]+),\s*p\.(\d+)\]", rag_ctx):
        chave = m.group(1).strip()
        pag   = m.group(2).strip()
        if chave not in paginas_por_fonte:
            paginas_por_fonte[chave] = []
        if pag not in paginas_por_fonte[chave]:
            paginas_por_fonte[chave].append(pag)

    if not paginas_por_fonte:
        return ""

    linhas = [
        f"- {formatar_fonte_abnt(fonte, pags)}"
        for fonte, pags in paginas_por_fonte.items()
    ]

    return "\n\n---\n**Referências bibliográficas**\n" + "\n".join(linhas)
