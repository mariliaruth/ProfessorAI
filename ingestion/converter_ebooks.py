"""
converter_ebooks.py
Converte arquivos .epub e .mobi para .pdf — e opcionalmente .pdf → .epub —
para compatibilidade com processar_biblioteca.py.

═══════════════════════════════════════════════════════════════
 USO
═══════════════════════════════════════════════════════════════
  # Converte todos os epub/mobi encontrados em Livros_base/
  python converter_ebooks.py

  # Converte um arquivo específico
  python converter_ebooks.py "Livros_base/Astrologia/livro.epub"

  # Converte sem sobrescrever arquivos já convertidos
  python converter_ebooks.py --pular-existentes

═══════════════════════════════════════════════════════════════
 ESTRATÉGIA DE CONVERSÃO
═══════════════════════════════════════════════════════════════
  .epub → .pdf   Python puro (ebooklib + reportlab)      ✔ funciona
  .mobi → .pdf   Calibre (ebook-convert) se instalado    ✔ instale para mobi
                 Fallback: extração direta do MOBI HTML  ⚠ qualidade variável

  Para melhor qualidade em mobi:
    brew install calibre          (macOS)
    sudo apt install calibre      (Ubuntu/Debian)

═══════════════════════════════════════════════════════════════
 RELAÇÃO COM processar_biblioteca.py
═══════════════════════════════════════════════════════════════
  Este script converte os arquivos NO MESMO diretório do original.
  Após converter, rode processar_biblioteca.py normalmente —
  ele vai detectar os novos PDFs e extrair o texto para o RAG.
"""

from __future__ import annotations

import argparse
import io
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import textwrap
import zlib
from pathlib import Path


# ── Configuração ───────────────────────────────────────────────────────────────

BOOK_DIR          = "./Livros_base"
MARGEM_PT         = 56          # ~2 cm em pontos (1pt = 1/72 polegada)
LARGURA_PT        = 595         # A4 largura
ALTURA_PT         = 842         # A4 altura
FONTE_CORPO       = 11
FONTE_TITULO      = 14
FONTE_CAP         = 12
ESPACAMENTO_LINHA = 16          # pontos entre linhas
CHARS_POR_LINHA   = 95          # aproximação para quebra de parágrafo


# ── Detecção de Calibre ────────────────────────────────────────────────────────

def _calibre_disponivel() -> bool:
    return _caminho_ebook_convert() is not None


def _caminho_ebook_convert() -> str | None:
    """Localiza o ebook-convert no PATH ou no app bundle do macOS."""
    env_path = os.getenv("EBOOK_CONVERT_PATH")
    if env_path and Path(env_path).exists():
        return env_path

    path = shutil.which("ebook-convert")
    if path:
        return path

    candidatos = [
        Path("/Applications/calibre.app/Contents/MacOS/ebook-convert"),
        Path.home() / "Applications/calibre.app/Contents/MacOS/ebook-convert",
        Path("/opt/homebrew/bin/ebook-convert"),
        Path("/usr/local/bin/ebook-convert"),
    ]
    for candidato in candidatos:
        if candidato.exists() and os.access(candidato, os.X_OK):
            return str(candidato)
    return None


# ── Conversão via Calibre (qualquer formato) ───────────────────────────────────

def converter_com_calibre(origem: Path, destino: Path) -> bool:
    """Usa ebook-convert do Calibre. Retorna True se bem-sucedido."""
    ebook_convert = _caminho_ebook_convert()
    if not ebook_convert:
        print("    ✖  Calibre nao encontrado.")
        return False
    cmd = [ebook_convert, str(origem), str(destino)]
    with tempfile.TemporaryDirectory(prefix="calibre-config-") as config_dir:
        env = os.environ.copy()
        env.setdefault("CALIBRE_CONFIG_DIRECTORY", config_dir)
        result = subprocess.run(cmd, capture_output=True, text=True, env=env)
    if result.returncode != 0:
        print(f"    ✖  Calibre falhou: {result.stderr[:200]}")
        return False
    return True


# ── Extração de texto de EPUB (Python puro) ───────────────────────────────────

def _extrair_texto_epub(caminho: Path) -> list[dict]:
    """
    Extrai o texto de um epub usando ebooklib.
    Retorna lista de dicts {"titulo": str, "texto": str} por capítulo.
    """
    import ebooklib
    from ebooklib import epub as eblib
    import html2text

    livro = eblib.read_epub(str(caminho), options={"ignore_ncx": True})

    conversor = html2text.HTML2Text()
    conversor.ignore_links      = True
    conversor.ignore_images     = True
    conversor.ignore_emphasis   = False
    conversor.body_width        = 0     # sem quebra forçada — deixa o reportlab fazer

    capitulos = []
    for item in livro.get_items_of_type(ebooklib.ITEM_DOCUMENT):
        html = item.get_content().decode("utf-8", errors="replace")
        texto = conversor.handle(html).strip()
        if len(texto) < 50:             # ignora páginas de crédito / em branco
            continue

        # Tenta extrair título do capítulo (<h1>, <h2>, <title>)
        titulo = ""
        m = re.search(r"<(?:h[12]|title)[^>]*>(.*?)</(?:h[12]|title)>", html, re.I | re.S)
        if m:
            titulo = re.sub(r"<[^>]+>", "", m.group(1)).strip()

        capitulos.append({"titulo": titulo, "texto": texto})

    return capitulos


# ── Geração de PDF com reportlab ───────────────────────────────────────────────

def _capitulos_para_pdf(capitulos: list[dict], destino: Path, titulo_livro: str = "") -> None:
    """Converte lista de capítulos em PDF usando reportlab."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, PageBreak, HRFlowable
    )
    from reportlab.lib.enums import TA_LEFT, TA_CENTER
    from reportlab.lib import colors

    doc = SimpleDocTemplate(
        str(destino),
        pagesize     = A4,
        leftMargin   = MARGEM_PT,
        rightMargin  = MARGEM_PT,
        topMargin    = MARGEM_PT,
        bottomMargin = MARGEM_PT,
        title        = titulo_livro,
    )

    estilos = getSampleStyleSheet()

    estilo_titulo_livro = ParagraphStyle(
        "TituloLivro",
        parent    = estilos["Heading1"],
        fontSize  = 18,
        leading   = 24,
        alignment = TA_CENTER,
        spaceAfter= 24,
    )
    estilo_capitulo = ParagraphStyle(
        "Capitulo",
        parent    = estilos["Heading2"],
        fontSize  = FONTE_CAP,
        leading   = 18,
        spaceAfter= 10,
        spaceBefore= 14,
    )
    estilo_corpo = ParagraphStyle(
        "Corpo",
        parent    = estilos["Normal"],
        fontSize  = FONTE_CORPO,
        leading   = ESPACAMENTO_LINHA,
        spaceAfter= 6,
        alignment = TA_LEFT,
    )

    story = []

    # Capa
    if titulo_livro:
        story.append(Spacer(1, 80))
        story.append(Paragraph(titulo_livro, estilo_titulo_livro))
        story.append(PageBreak())

    for cap in capitulos:
        if cap["titulo"]:
            story.append(Paragraph(_escapar_xml(cap["titulo"]), estilo_capitulo))
            story.append(HRFlowable(width="100%", thickness=0.5, color=colors.grey))
            story.append(Spacer(1, 6))

        # Divide em parágrafos pelo texto
        for bloco in cap["texto"].split("\n\n"):
            bloco = bloco.strip()
            if not bloco:
                continue
            # Linhas que começam com # são títulos residuais do markdown
            if bloco.startswith("#"):
                titulo_bloco = bloco.lstrip("# ").strip()
                story.append(Paragraph(_escapar_xml(titulo_bloco), estilo_capitulo))
            else:
                story.append(Paragraph(_escapar_xml(bloco), estilo_corpo))

        story.append(Spacer(1, 8))

    doc.build(story)


def _escapar_xml(texto: str) -> str:
    """Escapa caracteres especiais para uso no reportlab XML."""
    return (
        texto
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def epub_para_pdf(origem: Path, destino: Path) -> bool:
    """Converte .epub → .pdf usando Python puro. Retorna True se OK."""
    print(f"    → Extraindo texto do epub...")
    capitulos = _extrair_texto_epub(origem)
    if not capitulos:
        print(f"    ✖  Nenhum conteúdo extraído de {origem.name}")
        return False

    total_chars = sum(len(c["texto"]) for c in capitulos)
    print(f"    → {len(capitulos)} capítulos, {total_chars:,} caracteres")
    print(f"    → Gerando PDF...")
    _capitulos_para_pdf(capitulos, destino, titulo_livro=origem.stem)
    return True


# ── Extração de texto de MOBI (fallback sem Calibre) ──────────────────────────

def _extrair_html_mobi(caminho: Path) -> str | None:
    """
    Tenta extrair o HTML embutido num arquivo .mobi sem bibliotecas externas.
    Funciona para a maioria dos MOBI gerados por Calibre ou exportados do Kindle.
    Retorna string HTML ou None se falhar.
    """
    try:
        dados = caminho.read_bytes()
    except Exception:
        return None

    # O MOBI é baseado no formato PalmDB.
    # O conteúdo HTML comprimido fica nos registros após o cabeçalho.
    # Identificador mágico: bytes 60-68 devem ser "BOOKMOBI" ou "TEXtREAd"
    magic = dados[60:68]
    if magic not in (b"BOOKMOBI", b"TEXtREAd"):
        return None

    # Número de registros: offset 76 (uint16 big-endian)
    n_records = struct.unpack(">H", dados[76:78])[0]

    # Lista de offsets dos registros
    offsets = []
    for i in range(n_records):
        base = 78 + i * 8
        offset = struct.unpack(">I", dados[base:base + 4])[0]
        offsets.append(offset)
    offsets.append(len(dados))   # sentinela para calcular tamanho do último

    # Cabeçalho MOBI: offset do primeiro registro + 16 = início do cabeçalho MOBI
    r0 = offsets[0]
    # PalmDOC header: bytes 0-31 do registro 0
    # compression: uint16 offset r0
    compression = struct.unpack(">H", dados[r0:r0 + 2])[0]
    # text_length: uint32 offset r0+4
    text_length = struct.unpack(">I", dados[r0 + 4:r0 + 8])[0]
    # n_text_records: uint16 offset r0+8
    n_text = struct.unpack(">H", dados[r0 + 8:r0 + 10])[0]

    blocos = []
    for i in range(1, n_text + 1):
        if i >= len(offsets):
            break
        bloco = dados[offsets[i]: offsets[i + 1]]
        if compression == 2:            # PalmDOC LZ77
            bloco = _palmdoc_decompress(bloco)
        elif compression == 17480:      # Huffman/CDIC (raro, desiste)
            return None
        blocos.append(bloco)

    html_bytes = b"".join(blocos)
    # Às vezes há um byte de trailing nulo
    html_bytes = html_bytes.rstrip(b"\x00")

    try:
        return html_bytes.decode("utf-8", errors="replace")
    except Exception:
        return None


def _palmdoc_decompress(dados: bytes) -> bytes:
    """Descompressor PalmDOC LZ77 (usado em arquivos MOBI/PDB)."""
    resultado = bytearray()
    i = 0
    while i < len(dados):
        c = dados[i]
        i += 1
        if c == 0x00:
            resultado.append(0)
        elif c <= 0x08:
            resultado.extend(dados[i: i + c])
            i += c
        elif c <= 0x7F:
            resultado.append(c)
        elif c <= 0xBF:
            if i >= len(dados):
                break
            d = dados[i]; i += 1
            dist = ((c & 0x3F) << 2) | (d >> 6)
            ln   = (d & 0x3F) + 3
            pos  = len(resultado) - dist
            if pos < 0:
                pos = 0
            for _ in range(ln):
                if pos < len(resultado):
                    resultado.append(resultado[pos])
                else:
                    resultado.append(0x20)
                pos += 1
        else:
            resultado.append(0x20)      # espaço
            resultado.append(c & 0x7F)
    return bytes(resultado)


def mobi_para_pdf(origem: Path, destino: Path) -> bool:
    """
    Converte .mobi → .pdf.
    Ordem de tentativas:
      1. Calibre (ebook-convert) — melhor qualidade
      2. mobi (pip) — extrai book.html sem dependências externas
      3. Extração manual PalmDOC — fallback de último recurso
    """
    if _calibre_disponivel():
        print(f"    → Usando Calibre...")
        return converter_com_calibre(origem, destino)

    # ── Tentativa 2: biblioteca mobi (pip install mobi) ───────────────────────
    try:
        import mobi as mobi_lib
        import shutil as _shutil
        import html2text

        print(f"    → Usando biblioteca mobi (Python)...")
        tmpdir, html_path = mobi_lib.extract(str(origem))

        html_file = Path(html_path)
        if not html_file.exists():
            # Procura qualquer .html ou .htm no tmpdir
            candidatos = list(Path(tmpdir).rglob("*.html")) + list(Path(tmpdir).rglob("*.htm"))
            if not candidatos:
                raise FileNotFoundError("Nenhum HTML encontrado na extração MOBI")
            html_file = candidatos[0]

        html = html_file.read_text(encoding="utf-8", errors="replace")
        conversor = html2text.HTML2Text()
        conversor.ignore_links  = True
        conversor.ignore_images = True
        conversor.body_width    = 0
        texto = conversor.handle(html).strip()

        _shutil.rmtree(tmpdir, ignore_errors=True)   # limpa temp

        if len(texto) < 100:
            raise ValueError(f"Conteúdo insuficiente ({len(texto)} chars)")

        capitulos = [{"titulo": "", "texto": texto}]
        print(f"    → {len(texto):,} caracteres, gerando PDF...")
        _capitulos_para_pdf(capitulos, destino, titulo_livro=origem.stem)
        return True

    except Exception as e:
        print(f"    ⚠  mobi falhou ({e}) — tentando extração direta do MOBI...")

    # ── Tentativa 3: extração manual PalmDOC ─────────────────────────────────
    html = _extrair_html_mobi(origem)
    if not html:
        print(f"    ✖  Não foi possível extrair conteúdo de {origem.name}")
        print(f"       Para melhor resultado, instale o Calibre:")
        print(f"       macOS:  brew install calibre")
        print(f"       Linux:  sudo apt install calibre")
        return False

    import html2text
    conversor = html2text.HTML2Text()
    conversor.ignore_links  = True
    conversor.ignore_images = True
    conversor.body_width    = 0
    texto = conversor.handle(html).strip()

    if len(texto) < 100:
        print(f"    ✖  Conteúdo extraído insuficiente ({len(texto)} chars)")
        return False

    capitulos = [{"titulo": "", "texto": texto}]
    print(f"    → {len(texto):,} caracteres extraídos, gerando PDF...")
    _capitulos_para_pdf(capitulos, destino, titulo_livro=origem.stem)
    return True


# ── Pipeline principal ─────────────────────────────────────────────────────────

def converter_arquivo(origem: Path, pular_existentes: bool = True) -> bool:
    """Converte um arquivo para PDF. Retorna True se convertido com sucesso."""
    sufixo = origem.suffix.lower()

    if sufixo not in (".epub", ".mobi"):
        print(f"  ⏩ Ignorado (formato não suportado): {origem.name}")
        return False

    destino = origem.with_suffix(".pdf")

    if pular_existentes and destino.exists():
        print(f"  ⏩ Já existe: {destino.name}")
        return False

    print(f"  📖 Convertendo: {origem.name}")
    print(f"     → {destino.name}")

    sucesso = False
    if sufixo == ".epub":
        sucesso = epub_para_pdf(origem, destino)
    elif sufixo == ".mobi":
        sucesso = mobi_para_pdf(origem, destino)

    if sucesso:
        kb = destino.stat().st_size // 1024
        print(f"    ✅ PDF gerado ({kb} KB)")
    else:
        print(f"    ✖  Falha na conversão")

    return sucesso


def converter_pasta(raiz: Path, pular_existentes: bool = True) -> None:
    """Varre recursivamente uma pasta e converte todos os epub/mobi encontrados."""
    arquivos = sorted(raiz.rglob("*.epub")) + sorted(raiz.rglob("*.mobi"))

    if not arquivos:
        print(f"Nenhum arquivo .epub ou .mobi encontrado em {raiz}")
        return

    print(f"Encontrados {len(arquivos)} arquivo(s) para converter.\n")
    convertidos = 0
    falhas      = 0

    for arq in arquivos:
        ok = converter_arquivo(arq, pular_existentes=pular_existentes)
        if ok:
            convertidos += 1
        elif arq.with_suffix(".pdf").exists() and pular_existentes:
            pass     # já existia, não conta como falha
        else:
            falhas += 1

    print(f"\n{'─'*60}")
    print(f"✅ Convertidos: {convertidos}")
    if falhas:
        print(f"✖  Falhas:      {falhas}")
    print(f"\nPróximo passo: python processar_biblioteca.py")


# ── Entrada ───────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Converte epub/mobi para PDF para uso com processar_biblioteca.py",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""
            Exemplos:
              python converter_ebooks.py
              python converter_ebooks.py "Livros_base/Astrologia/livro.epub"
              python converter_ebooks.py --pular-existentes
        """),
    )
    parser.add_argument(
        "arquivo",
        nargs="?",
        help="Arquivo específico para converter (opcional). "
             "Se omitido, converte tudo em Livros_base/",
    )
    parser.add_argument(
        "--pular-existentes",
        action="store_true",
        default=True,
        help="Não reconverte se o PDF já existir (padrão: ativo)",
    )
    parser.add_argument(
        "--forcar",
        action="store_true",
        default=False,
        help="Reconverte mesmo se o PDF já existir",
    )

    args = parser.parse_args()
    pular = not args.forcar

    if args.arquivo:
        caminho = Path(args.arquivo)
        if not caminho.exists():
            print(f"Arquivo não encontrado: {caminho}")
            sys.exit(1)
        converter_arquivo(caminho, pular_existentes=pular)
    else:
        converter_pasta(Path(BOOK_DIR), pular_existentes=pular)
