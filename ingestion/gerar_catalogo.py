"""
gerar_catalogo.py
Gera catalogo_gerado.json automaticamente a partir dos arquivos em backup_textos/.

Estratégia por prioridade (da mais barata para a mais cara):
  1. Metadados do PDF (pypdf)         — grátis, instantâneo
  2. Heurística no nome do arquivo    — grátis, cobre a maioria dos casos
  3. LLM gpt-4o-mini                  — ~$0.0001/livro, para casos ambíguos

Uso:
  python gerar_catalogo.py            # só novos livros (pula já catalogados)
  python gerar_catalogo.py --todos    # reprocessa todos
  python gerar_catalogo.py --seco     # mostra o que faria, sem salvar
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# ── Caminhos ──────────────────────────────────────────────────────────────────

BACKUP_DIR  = Path("./backup_textos")
LIVROS_DIR  = Path("./Livros_base")
OUTPUT_PATH = Path("./catalogo_gerado.json")


# ── Helpers de I/O ────────────────────────────────────────────────────────────

def _carregar_existente() -> dict:
    if OUTPUT_PATH.exists():
        return json.loads(OUTPUT_PATH.read_text(encoding="utf-8"))
    return {}


def _salvar(catalogo: dict) -> None:
    OUTPUT_PATH.write_text(
        json.dumps(catalogo, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


# ── Camada 1: metadados do PDF ────────────────────────────────────────────────

def _encontrar_pdf(fonte_key: str) -> Path | None:
    """Procura o PDF cujo stem é igual a fonte_key em qualquer subpasta de Livros_base/."""
    for pdf in LIVROS_DIR.rglob("*.pdf"):
        if pdf.stem == fonte_key:
            return pdf
    return None


def _extrair_metadata_pdf(fonte_key: str) -> dict | None:
    """Tenta extrair título e autor dos metadados XMP/Info do PDF."""
    pdf_path = _encontrar_pdf(fonte_key)
    if not pdf_path:
        return None
    try:
        from pypdf import PdfReader
        reader = PdfReader(str(pdf_path), strict=False)
        info   = reader.metadata or {}
        titulo = (info.get("/Title") or "").strip()
        autor  = (info.get("/Author") or "").strip()

        # Descarta metadados claramente inúteis
        if not titulo or len(titulo) < 4:
            return None
        if re.fullmatch(r"[Uu]nknown|[Nn]/[Aa]|[-_]+", titulo):
            return None

        return {"titulo": titulo, "autor": autor, "_via": "pdf_metadata"}
    except Exception:
        return None


# ── Camada 2: heurística no nome do arquivo ───────────────────────────────────

def _heuristica(fonte_key: str) -> dict | None:
    """
    Tenta extrair título e autor a partir de padrões comuns de nomes de arquivo.
    Retorna None se não encontrar nada confiável.
    """
    s = fonte_key

    # Padrão z-library: "Title (Author) (site1, site2, ...)"
    # Exemplo: "Synthesis  Counseling in Astrology (Noel Tyl) (z-library.sk, ...)"
    m = re.match(
        r"^(.+?)\s+\(([^)]+)\)\s+\([^)]*(?:z-lib|library|1lib|z-lib\.sk)[^)]*\)",
        s, re.I,
    )
    if m:
        titulo = m.group(1).strip()
        autor  = m.group(2).strip()
        # Descarta se o "autor" parece ser parte do título (sem sobrenome visível)
        if len(autor.split()) >= 2:
            return {"titulo": titulo, "autor": autor, "_via": "heuristica_zlibrary"}

    # Padrão "Título - Autor" (com ou sem underscores)
    # Exemplos: "Jung e o Tarô - Sallie Nichols"
    #            "Essential_Astrology_-_Amy_Herring"
    s_clean = re.sub(r"_-_", " - ", s).replace("_", " ")
    if " - " in s_clean:
        partes = s_clean.split(" - ", 1)
        titulo = partes[0].strip()
        autor  = partes[1].strip()
        # Autor deve parecer um nome (pelo menos 2 palavras ou 1 sobrenome)
        if autor and not re.search(r"\d", autor) and len(autor) > 2:
            return {"titulo": titulo, "autor": autor, "_via": "heuristica_dash"}

    # Padrão "título_Sobrenome" (underscore antes do sobrenome do autor)
    # Exemplo: "A book on Mathematical astrology_Bansal"
    m = re.match(r"^(.+?)_([A-Z][a-z]+)$", s)
    if m:
        return {
            "titulo": m.group(1).replace("_", " ").strip(),
            "autor":  m.group(2).strip(),
            "_via":   "heuristica_underscore_author",
        }

    # Padrão slug simples: "steven-forrest-inner-sky"
    # Tenta separar autor (primeiros 2 tokens) de título (resto) quando slug é limpo
    if re.match(r"^[a-z][a-z0-9-]+$", s):
        partes = s.split("-")
        if len(partes) >= 4:
            # Assume "nome-sobrenome-palavra-palavra..." → autor = partes[:2]
            autor  = " ".join(p.title() for p in partes[:2])
            titulo = " ".join(p.title() for p in partes[2:])
            return {"titulo": titulo, "autor": autor, "_via": "heuristica_slug", "_confidence": "low"}

    return None


# ── Camada 3: LLM (gpt-4o-mini) ──────────────────────────────────────────────

def _chamar_llm(fonte_key: str) -> dict:
    """
    Usa gpt-4o-mini para extrair título e autor do nome do arquivo.
    Último recurso — ~$0.0001 por chamada.
    """
    from openai import OpenAI
    client = OpenAI()

    prompt = (
        "Dado o seguinte nome de arquivo de livro (sem extensão), "
        "extraia o título e o autor. "
        "Retorne APENAS JSON com as chaves 'titulo' e 'autor'. "
        "Se não conseguir identificar o autor, use string vazia.\n\n"
        f"Nome do arquivo: {fonte_key}"
    )

    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
        max_tokens=120,
        temperature=0,
    )
    dados = json.loads(resp.choices[0].message.content)
    dados["_via"] = "llm_gpt4o_mini"
    return dados


# ── Pipeline principal ────────────────────────────────────────────────────────

def _listar_fontes() -> list[str]:
    """Retorna todos os stems de JSON em backup_textos/ (exceto .parcial)."""
    return sorted(
        p.stem
        for p in BACKUP_DIR.rglob("*.json")
        if ".parcial" not in p.name
    )


def _processar_fonte(fonte_key: str, verbose: bool = True) -> dict:
    """
    Tenta extrair título/autor por todas as camadas.
    Sempre retorna um dict com pelo menos 'titulo' e 'autor'.
    """
    # 1. Metadados PDF
    resultado = _extrair_metadata_pdf(fonte_key)
    if resultado:
        if verbose:
            print(f"    [PDF metadata] {resultado['titulo']} — {resultado['autor']}")
        return resultado

    # 2. Heurística
    resultado = _heuristica(fonte_key)
    if resultado and resultado.get("_confidence") != "low":
        if verbose:
            via = resultado.get("_via", "heuristica")
            print(f"    [{via}] {resultado['titulo']} — {resultado['autor']}")
        return resultado

    # 3. LLM
    if verbose:
        print(f"    [LLM] consultando gpt-4o-mini...")
    try:
        resultado = _chamar_llm(fonte_key)
        if verbose:
            print(f"    [LLM] {resultado.get('titulo','')} — {resultado.get('autor','')}")
        return resultado
    except Exception as e:
        if verbose:
            print(f"    [LLM] falhou ({e}) — usando fallback slug")
        # Fallback absoluto: limpa o slug
        titulo = re.sub(r"\([^)]*\)", "", fonte_key)
        titulo = re.sub(r"[_-]", " ", titulo).strip().title()
        return {"titulo": titulo, "autor": "", "_via": "fallback_slug"}


def gerar(reprocessar_todos: bool = False, seco: bool = False) -> None:
    fontes = _listar_fontes()
    existente = _carregar_existente()

    novas  = 0
    puladas = 0

    for fonte_key in fontes:
        if not reprocessar_todos and fonte_key in existente:
            puladas += 1
            continue

        print(f"\n📖 {fonte_key}")
        resultado = _processar_fonte(fonte_key)

        # Remove chaves internas antes de salvar
        entrada = {k: v for k, v in resultado.items() if not k.startswith("_")}

        if not seco:
            existente[fonte_key] = entrada
            _salvar(existente)   # salva incrementalmente (safe se interrompido)

        novas += 1

    print(f"\n{'─'*60}")
    print(f"✅ Novas entradas: {novas}  |  Já existentes (puladas): {puladas}")
    print(f"📄 Salvo em: {OUTPUT_PATH}")

    if seco:
        print("   (modo --seco: nenhum arquivo foi modificado)")


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Gera catalogo_gerado.json automaticamente.")
    parser.add_argument("--todos",  action="store_true", help="Reprocessa todos os livros")
    parser.add_argument("--seco",   action="store_true", help="Mostra o que faria sem salvar")
    args = parser.parse_args()

    gerar(reprocessar_todos=args.todos, seco=args.seco)
