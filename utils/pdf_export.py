# pdf_export.py
# Gera o PDF do mapa natal com três partes:
#   1. Carta pessoal de apresentação
#   2. Imagem do mapa SVG + dados técnicos
#   3. Interpretação astrológica completa

import io
import re
import tempfile
import os
from datetime import date
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, HRFlowable,
    KeepTogether, PageBreak,
)
from reportlab.platypus.flowables import Flowable
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_JUSTIFY
from svglib.svglib import svg2rlg
from reportlab.graphics import renderPDF


# ── Paleta de cores ────────────────────────────────────────────────────────────

ROXO_ESCURO  = colors.HexColor("#3b0764")
ROXO         = colors.HexColor("#7c3aed")
ROXO_CLARO   = colors.HexColor("#ede9fe")
CINZA        = colors.HexColor("#64748b")
PRETO        = colors.HexColor("#1e1b4b")
BRANCO       = colors.white


# ── Pré-processamento do SVG ──────────────────────────────────────────────────

def _resolver_css_vars(svg: str) -> str:
    """
    Substitui CSS custom properties (var(--name)) pelos valores definidos
    no bloco :root do SVG — necessário porque o svglib não processa CSS vars.
    """
    # Extrai todas as variáveis do bloco :root
    root_match = re.search(r":root\s*\{([^}]+)\}", svg, re.DOTALL)
    if not root_match:
        return svg
    variaveis: dict[str, str] = {}
    for m in re.finditer(r"--([\w-]+)\s*:\s*([^;]+);", root_match.group(1)):
        variaveis[m.group(1).strip()] = m.group(2).strip()

    # Substitui var(--name) pelo valor correspondente (máximo 3 passagens p/ aninhados)
    for _ in range(3):
        def _repl(m):
            nome = m.group(1).strip()
            return variaveis.get(nome, "#888888")
        svg_novo = re.sub(r"var\(\s*--([\w-]+)\s*\)", _repl, svg)
        if svg_novo == svg:
            break
        svg = svg_novo
    return svg


def _limpar_unicode_pdf(texto: str) -> str:
    """
    Remove/substitui caracteres Unicode não suportados pelas fontes
    embutidas do ReportLab (Helvetica/Courier suportam apenas Latin-1).
    Símbolos astrológicos e glyphs especiais são mapeados para ASCII.
    """
    mapa = {
        # Nodos lunares
        "☊": "(Nodo Norte)", "☋": "(Nodo Sul)",
        # Pontos
        "⚷": "(Quíron)", "⚸": "(Lilith)", "⚹": "(*)",
        # Aspectos
        "☌": "conjunção", "☍": "oposição", "△": "trígono",
        "□": "quadratura", "⚹": "sextil", "⚻": "quincúncio",
        # Planetas (às vezes usados como glyph)
        "☉": "Sol", "☽": "Lua", "☿": "Mercúrio", "♀": "Vênus",
        "♂": "Marte", "♃": "Júpiter", "♄": "Saturno",
        "♅": "Urano", "♆": "Netuno", "♇": "Plutão",
        # Signos zodiacais
        "♈": "Áries", "♉": "Touro", "♊": "Gêmeos", "♋": "Câncer",
        "♌": "Leão", "♍": "Virgem", "♎": "Libra", "♏": "Escorpião",
        "♐": "Sagitário", "♑": "Capricórnio", "♒": "Aquário", "♓": "Peixes",
        # Quadradinhos coloridos do kerykeion (símbolo de signo no mapa)
        "■": "", "□": "", "▪": "", "▫": "",
        "🟧": "", "🟦": "", "🟥": "", "🟩": "", "⬛": "", "⬜": "",
    }
    for src, dst in mapa.items():
        texto = texto.replace(src, dst)
    # Remove qualquer char fora de Latin-1 que sobrou
    return texto.encode("latin-1", errors="ignore").decode("latin-1")


# ── Flowable para SVG ─────────────────────────────────────────────────────────

class SvgFlowable(Flowable):
    """Renderiza um SVG como flowable do ReportLab."""

    def __init__(self, svg_string: str, max_width: float, max_height: float):
        super().__init__()
        self._drawing = None
        self._w = max_width
        self._h = max_height

        try:
            svg_proc = _resolver_css_vars(svg_string)
            with tempfile.NamedTemporaryFile(suffix=".svg", delete=False, mode="w", encoding="utf-8") as f:
                f.write(svg_proc)
                tmp_path = f.name
            drawing = svg2rlg(tmp_path)
            os.unlink(tmp_path)

            if drawing:
                scale = min(max_width / drawing.width, max_height / drawing.height)
                drawing.width  *= scale
                drawing.height *= scale
                drawing.transform = (scale, 0, 0, scale, 0, 0)
                self._drawing = drawing
                self._w = drawing.width
                self._h = drawing.height
            else:
                print("  ⚠️  SvgFlowable: svg2rlg retornou None")
        except Exception as e:
            print(f"  ⚠️  SvgFlowable: {e}")

    def wrap(self, availWidth, availHeight):
        return self._w, self._h

    def draw(self):
        if self._drawing:
            renderPDF.draw(self._drawing, self.canv, 0, 0)


# ── Estilos ────────────────────────────────────────────────────────────────────

def _estilos():
    base = getSampleStyleSheet()

    titulo = ParagraphStyle(
        "Titulo",
        parent=base["Title"],
        fontSize=22,
        textColor=ROXO_ESCURO,
        spaceAfter=4,
        alignment=TA_CENTER,
        fontName="Helvetica-Bold",
    )
    subtitulo = ParagraphStyle(
        "Subtitulo",
        parent=base["Normal"],
        fontSize=11,
        textColor=ROXO,
        spaceAfter=16,
        alignment=TA_CENTER,
        fontName="Helvetica",
    )
    secao = ParagraphStyle(
        "Secao",
        parent=base["Heading2"],
        fontSize=14,
        textColor=ROXO_ESCURO,
        spaceBefore=18,
        spaceAfter=6,
        fontName="Helvetica-Bold",
        borderPad=4,
    )
    corpo = ParagraphStyle(
        "Corpo",
        parent=base["Normal"],
        fontSize=11,
        textColor=PRETO,
        leading=17,
        spaceAfter=8,
        alignment=TA_JUSTIFY,
        fontName="Helvetica",
    )
    mono = ParagraphStyle(
        "Mono",
        parent=base["Normal"],
        fontSize=9,
        textColor=colors.HexColor("#374151"),
        leading=13,
        fontName="Courier",
        backColor=colors.HexColor("#f8f7ff"),
        borderPad=6,
        spaceAfter=4,
    )
    rodape = ParagraphStyle(
        "Rodape",
        parent=base["Normal"],
        fontSize=8,
        textColor=CINZA,
        alignment=TA_CENTER,
        fontName="Helvetica-Oblique",
    )

    return titulo, subtitulo, secao, corpo, mono, rodape


# ── Conversão de markdown simplificada ────────────────────────────────────────

def _md_para_paragraph(texto: str, estilo) -> list:
    """
    Converte subset de markdown para parágrafos ReportLab.
    Suporta: **negrito**, *itálico*, # cabeçalhos, --- divisores, listas com -.
    """
    _, _, secao_style, corpo_style, _, _ = _estilos()
    paragraphs = []

    for linha in texto.split("\n"):
        l = linha.strip()
        if not l:
            paragraphs.append(Spacer(1, 4))
            continue

        if l.startswith("---") and len(l) <= 6:
            paragraphs.append(HRFlowable(width="100%", thickness=0.5, color=ROXO_CLARO, spaceAfter=6))
            continue

        # Cabeçalhos
        nivel = 0
        while nivel < len(l) and l[nivel] == "#":
            nivel += 1
        if nivel > 0:
            texto_h = l[nivel:].strip()
            tamanho = max(10, 15 - nivel * 2)
            h_style = ParagraphStyle(
                f"H{nivel}",
                fontSize=tamanho,
                textColor=ROXO_ESCURO if nivel <= 2 else ROXO,
                fontName="Helvetica-Bold",
                spaceBefore=12,
                spaceAfter=4,
                leading=tamanho + 4,
            )
            paragraphs.append(Paragraph(_fmt_inline(texto_h), h_style))
            continue

        # Lista
        if l.startswith("- ") or l.startswith("• "):
            conteudo = l[2:]
            lista_style = ParagraphStyle(
                "Lista",
                parent=corpo_style,
                leftIndent=16,
                bulletIndent=4,
                spaceAfter=3,
            )
            paragraphs.append(Paragraph(f"• {_fmt_inline(conteudo)}", lista_style))
            continue

        paragraphs.append(Paragraph(_fmt_inline(l), estilo))

    return paragraphs


def _fmt_inline(texto: str) -> str:
    """Converte **negrito** e *itálico* para tags ReportLab."""
    texto = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", texto)
    texto = re.sub(r"\*(.+?)\*",     r"<i>\1</i>", texto)
    # Escapa caracteres especiais do ReportLab que não foram marcados
    texto = texto.replace("&", "&amp;").replace("<b>", "<b>").replace("</b>", "</b>")
    # Revert double-escape de tags válidas
    texto = texto.replace("&lt;b&gt;", "<b>").replace("&lt;/b&gt;", "</b>")
    texto = texto.replace("&lt;i&gt;", "<i>").replace("&lt;/i&gt;", "</i>")
    return texto


# ── Gerador principal ─────────────────────────────────────────────────────────

def _extrair_fontes(rag_contexto: str) -> list[str]:
    """
    Extrai fontes do contexto RAG, agrupando páginas por livro.
    Formato de entrada: '[nome-do-livro, p.N]\\ntrecho'
    Formato de saída:   ['nome do livro (pp. 10, 42, 93)', ...]
    """
    import re as _re
    from collections import OrderedDict
    paginas_por_livro: dict[str, list[str]] = OrderedDict()
    for match in _re.finditer(r"\[([^\]]+),\s*p\.(\d+)\]", rag_contexto):
        nome  = match.group(1).strip()
        pag   = match.group(2).strip()
        chave = nome.lower()
        if chave not in paginas_por_livro:
            paginas_por_livro[chave] = {"nome": nome, "pags": []}
        if pag not in paginas_por_livro[chave]["pags"]:
            paginas_por_livro[chave]["pags"].append(pag)

    fontes = []
    for dados in paginas_por_livro.values():
        pags = ", ".join(dados["pags"])
        prefixo = "pp." if len(dados["pags"]) > 1 else "p."
        fontes.append(f"{dados['nome']} ({prefixo} {pags})")
    return fontes


def gerar_pdf_mapa(
    nome: str,
    birth_date: str,
    city: str,
    mapa_texto: str,
    mapa_svg: str,
    leitura_astrologica: str,
    rag_contexto: str = "",
    titulo_consulta: str = "Mapa Natal",
    autor: str = "Oráculo Digital",
) -> str:
    """
    Gera o PDF com três partes e retorna o caminho do arquivo temporário.

    Args:
        nome:               Nome do consulente
        birth_date:         Data de nascimento ou info da consulta
        city:               Cidade (ou informação extra da consulta)
        mapa_texto:         Dados técnicos (texto puro; pode ser vazio)
        mapa_svg:           SVG do mapa gerado pelo kerykeion (pode ser vazio)
        leitura_astrologica: Interpretação do Astrólogo (markdown)
        rag_contexto:       Contexto RAG bruto para gerar seção de fontes
        titulo_consulta:    Tipo da consulta (ex: "Mapa Natal", "Trânsitos", ...)
        autor:              Nome de quem gerou o mapa

    Returns:
        Caminho absoluto do arquivo PDF gerado em diretório temporário.
    """
    _DESCRICOES: dict[str, str] = {
        "Mapa Natal":               "Análise completa da sua personalidade e potencial de vida",
        "Trânsitos Astrológicos":   "Influências planetárias sobre o seu mapa natal no período",
        "Sinastria":                "Análise de compatibilidade e dinâmica entre dois mapas",
        "Consulta Oracular":        "Leitura integrada pelos oráculos de astrologia, tarot e numerologia",
    }
    descricao_consulta = _DESCRICOES.get(titulo_consulta, "Leitura gerada por Inteligência Artificial")

    nome_arquivo = re.sub(r"[^\w\s-]", "", nome or "consulta").strip().replace(" ", "_")
    tmp_path = os.path.join(tempfile.gettempdir(), f"oraculo_{nome_arquivo}.pdf")

    doc = SimpleDocTemplate(
        tmp_path,
        pagesize=A4,
        leftMargin=2.5 * cm,
        rightMargin=2.5 * cm,
        topMargin=2.5 * cm,
        bottomMargin=2.5 * cm,
        title=f"{titulo_consulta} — {nome}",
        author=autor,
    )

    titulo_s, subtitulo_s, secao_s, corpo_s, mono_s, rodape_s = _estilos()
    largura_util = A4[0] - 5 * cm   # largura da página menos margens

    story = []

    # ══════════════════════════════════════════════════════════════════════════
    # PARTE 1 — Carta pessoal
    # ══════════════════════════════════════════════════════════════════════════

    story.append(Spacer(1, 1 * cm))
    story.append(Paragraph("🔮 Oráculo Digital", titulo_s))
    story.append(Paragraph(descricao_consulta, subtitulo_s))
    story.append(HRFlowable(width="100%", thickness=1.5, color=ROXO, spaceAfter=24))

    hoje = date.today().strftime("%d/%m/%Y")
    nome_exibir = nome or "você"

    _INTRO: dict[str, str] = {
        "Mapa Natal": (
            f"Fiz o seu mapa natal e aproveitei para usá-lo em um projeto que estou desenvolvendo. "
            f"Usei Inteligência Artificial para unir a precisão dos cálculos matemáticos com a "
            f"profundidade dos livros de referência em astrologia."
        ),
        "Trânsitos Astrológicos": (
            f"Calculei os trânsitos astrológicos sobre o seu mapa natal para o período solicitado. "
            f"A interpretação foi gerada por IA consultando obras especializadas de astrologia."
        ),
        "Sinastria": (
            f"Calculei a sinastria entre os dois mapas natais informados. "
            f"A análise de compatibilidade foi gerada por IA consultando obras especializadas."
        ),
        "Consulta Oracular": (
            f"Realizei uma consulta oracular integrando astrologia, tarot e numerologia. "
            f"As leituras foram geradas por IA consultando obras especializadas de cada área."
        ),
    }
    intro_texto = _INTRO.get(titulo_consulta, _INTRO["Consulta Oracular"])

    carta = f"""
Oi, <b>{nome_exibir}</b>!

{intro_texto}

Em vez de usar respostas prontas de internet, criei um sistema (usando Python e IA) que "lê" obras de referência para gerar interpretações. É como se a tecnologia consultasse uma biblioteca especializada para explicar cada detalhe de forma única.

Nas próximas páginas você vai encontrar:
"""
    for linha in carta.strip().split("\n"):
        l = linha.strip()
        if l:
            story.append(Paragraph(_fmt_inline(l), corpo_s))
        else:
            story.append(Spacer(1, 6))

    fontes_bib = _extrair_fontes(rag_contexto)
    _ITENS_CARTA: dict[str, list[str]] = {
        "Mapa Natal": [
            "O <b>mapa natal completo</b> com a posição de todos os planetas e aspectos",
            "Uma <b>interpretação psicológica linha a linha</b> gerada pelo sistema",
            "As <b>fontes bibliográficas</b> consultadas para enriquecer a leitura",
        ],
        "Trânsitos Astrológicos": [
            "A posição dos <b>planetas em trânsito</b> sobre o mapa natal no período",
            "Uma <b>interpretação das influências</b> gerada pelo sistema",
            "As <b>fontes bibliográficas</b> consultadas para enriquecer a leitura",
        ],
        "Sinastria": [
            "A <b>comparação entre os dois mapas natais</b> e seus principais pontos de contato",
            "Uma <b>análise de dinâmica e compatibilidade</b> gerada pelo sistema",
            "As <b>fontes bibliográficas</b> consultadas para enriquecer a leitura",
        ],
        "Consulta Oracular": [
            "A <b>leitura integrada</b> pelos oráculos ativados (astrologia, tarot e/ou numerologia)",
            "A <b>síntese final do Mentor</b> unindo todas as visões",
            "As <b>fontes bibliográficas</b> consultadas para enriquecer a leitura",
        ],
    }
    itens_carta = _ITENS_CARTA.get(titulo_consulta, _ITENS_CARTA["Consulta Oracular"])
    for item in itens_carta:
        story.append(Paragraph(f"• {item}", ParagraphStyle(
            "CartaItem", parent=corpo_s, leftIndent=16, spaceAfter=4,
        )))

    story.append(Spacer(1, 12))
    story.append(Paragraph(
        f"Gerado em {hoje} · {autor}",
        rodape_s,
    ))

    # ══════════════════════════════════════════════════════════════════════════
    # PARTE 2 — Mapa SVG + dados técnicos
    # ══════════════════════════════════════════════════════════════════════════

    story.append(PageBreak())
    story.append(Paragraph(titulo_consulta, titulo_s))
    if nome and birth_date:
        story.append(Paragraph(
            f"{nome} · {birth_date}{(' · ' + city) if city else ''}",
            subtitulo_s,
        ))
    story.append(HRFlowable(width="100%", thickness=1.5, color=ROXO, spaceAfter=16))

    # Imagem do mapa
    if mapa_svg and mapa_svg.strip().startswith("<"):
        svg_flow = SvgFlowable(mapa_svg, max_width=largura_util, max_height=14 * cm)
        story.append(KeepTogether([svg_flow]))
        story.append(Spacer(1, 16))

    # Dados técnicos
    story.append(Paragraph("Dados Técnicos", secao_s))
    story.append(HRFlowable(width="100%", thickness=0.5, color=ROXO_CLARO, spaceAfter=8))

    if mapa_texto:
        for linha in mapa_texto.split("\n"):
            story.append(Paragraph(_limpar_unicode_pdf(linha) or " ", mono_s))

    # ══════════════════════════════════════════════════════════════════════════
    # PARTE 3 — Interpretação astrológica
    # ══════════════════════════════════════════════════════════════════════════

    if leitura_astrologica and leitura_astrologica.strip():
        _TITULO_PARTE3: dict[str, str] = {
            "Mapa Natal":             "Interpretação Astrológica",
            "Trânsitos Astrológicos": "Interpretação dos Trânsitos",
            "Sinastria":              "Análise de Sinastria",
            "Consulta Oracular":      "Leitura Oracular",
        }
        story.append(PageBreak())
        story.append(Paragraph(_TITULO_PARTE3.get(titulo_consulta, "Leitura"), titulo_s))
        story.append(Paragraph(
            "Leitura gerada por Inteligência Artificial com base em livros especializados",
            subtitulo_s,
        ))
        story.append(HRFlowable(width="100%", thickness=1.5, color=ROXO, spaceAfter=16))

        paragrafos = _md_para_paragraph(leitura_astrologica, corpo_s)
        story.extend(paragrafos)

        # Seção de fontes bibliográficas
        if fontes_bib:
            story.append(Spacer(1, 12))
            story.append(HRFlowable(width="100%", thickness=0.5, color=ROXO_CLARO, spaceAfter=8))
            story.append(Paragraph("Fontes Consultadas", secao_s))
            for fonte in fontes_bib:
                story.append(Paragraph(f"• {fonte}", ParagraphStyle(
                    "BibItem", parent=corpo_s, leftIndent=16, spaceAfter=3, fontSize=10,
                )))

    # ── Build ─────────────────────────────────────────────────────────────────
    doc.build(story)
    return tmp_path
