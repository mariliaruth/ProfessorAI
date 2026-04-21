# processar_biblioteca.py
# Extrai texto de PDFs (nativos ou imagéticos) e salva em backup_textos/
# O texto é limpo de artefatos OCR/Gemini antes de ser salvo.

import os
import re
import json
import random
import time
from pathlib import Path
from pdf2image import convert_from_path
from pdf2image.exceptions import PDFPageCountError
import pytesseract
from langchain_community.document_loaders import PyPDFLoader
from dotenv import load_dotenv

load_dotenv()

import google.generativeai as genai
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
model = genai.GenerativeModel("gemini-2.5-flash")

#ROOT_DIR = Path(__file__).resolve().parent.parent
ROOT_DIR = Path().resolve()
while not (ROOT_DIR / "Livros_base").exists():
    ROOT_DIR = ROOT_DIR.parent
    
BOOK_DIR   = ROOT_DIR / "Livros_base"
BACKUP_DIR = ROOT_DIR / "backup_textos"
MAX_PAGINAS_OCR = 5

# ── Prompt limpo: sem pedir identificação de idioma nem cabeçalhos meta ────────
PROMPT = """Transcreva o texto desta página exatamente como está escrito.
- Mantenha todos os termos técnicos originais.
- NÃO escreva cabeçalhos, introduções ou observações sobre a página.
- NÃO diga "o idioma é X" nem "o texto diz".
- Se houver uma figura, diagrama ou ilustração: descreva o CONTEÚDO SIMBÓLICO
  (ex: quais planetas aparecem, quais signos, quais símbolos, o que a carta de
  Tarot representa). NÃO descreva o layout visual (posição na página, formato
  geométrico, cores, tamanho).
- Comece diretamente pelo conteúdo do texto."""


# ── Limpeza de artefatos ───────────────────────────────────────────────────────

# Padrões gerados pelo Gemini quando o prompt anterior pedia "identifique o idioma"
_ARTEFATOS = [
    # Cabeçalhos meta do Gemini
    r"(?im)^\s*\*{0,2}Identificação do Idioma[:\*]*.*$",
    r"(?im)^\s*\*{0,2}O idioma d[ae]sta página é[^\.]*\.\s*$",
    r"(?im)^\s*\*{0,2}Transcrição Fiel do Texto[:\*]*.*$",
    r"(?im)^\s*\*{0,2}Descrição Detalhada dos Diagramas[:/\*]*.*$",
    r"(?im)^\s*\*{0,2}Símbolo[s]?[:\*].*$",
    r"(?im)^\s*\*{0,2}Notas Adicionais[:\*].*$",
    # Linhas de número de página isolado (ex: "132\n" ou "  132  \n")
    r"(?m)^\s*\d{1,4}\s*$",
    # Linhas em branco excessivas (mais de duas seguidas)
    r"\n{3,}",
]


def limpar_texto(texto: str) -> str:
    """Remove artefatos comuns de OCR/Gemini do texto extraído."""
    for padrao in _ARTEFATOS:
        substituicao = "\n" if "3," in padrao else ""
        texto = re.sub(padrao, substituicao, texto)
    # Normaliza espaços e quebras
    texto = re.sub(r" {2,}", " ", texto)
    texto = re.sub(r"\n{3,}", "\n\n", texto)
    return texto.strip()


# ── Detecção de PDF imagético ──────────────────────────────────────────────────

def pdf_e_imagetico(path, n_paginas=5, min_chars_por_pagina=100):
    """Retorna True se o PDF não tem camada de texto (é escaneado)."""
    try:
        loader = PyPDFLoader(str(path))
        paginas = loader.load_and_split()
    except Exception as e:
        print(f"  ⚠️  Não foi possível ler com PyPDF ({type(e).__name__}), assumindo imagético...")
        return True
    if not paginas:
        return True
    indices = random.sample(range(len(paginas)), min(n_paginas, len(paginas)))
    amostra = [paginas[i] for i in indices]
    media_chars = sum(len(p.page_content.strip()) for p in amostra) / len(amostra)
    return media_chars < min_chars_por_pagina


# ── Extração de PDF nativo (tem camada de texto) ──────────────────────────────

def extrair_texto_simples(path, backup_path):
    parcial_path = backup_path.with_suffix(".parcial.json")
    resultado = []
    paginas_feitas = set()

    if parcial_path.exists():
        with open(parcial_path, encoding="utf-8") as f:
            resultado = json.load(f)
            paginas_feitas = {r["pagina"] for r in resultado}
        print(f"  Retomando ({len(paginas_feitas)} páginas já feitas)")

    loader = PyPDFLoader(str(path))
    pages = loader.load_and_split()

    for i, p in enumerate(pages):
        num = i + 1
        if num not in paginas_feitas:
            texto = limpar_texto(p.page_content)
            resultado.append({"pagina": num, "texto": texto})
            with open(parcial_path, "w", encoding="utf-8") as f:
                json.dump(resultado, f, ensure_ascii=False, indent=2)
        del p

    if parcial_path.exists():
        parcial_path.unlink()

    return resultado


# ── Extração de PDF imagético (OCR / Gemini Vision) ──────────────────────────

def _contar_paginas(path) -> int | None:
    """Tenta contar as páginas do PDF por dois métodos diferentes."""
    # Método 1: pdfinfo (poppler)
    try:
        from pdf2image import pdfinfo_from_path
        return pdfinfo_from_path(path)["Pages"]
    except Exception:
        pass
    # Método 2: PyPDF (mais tolerante a PDFs malformados)
    try:
        from langchain_community.document_loaders import PyPDFLoader
        paginas = PyPDFLoader(str(path)).load_and_split()
        return len(paginas) if paginas else None
    except Exception:
        pass
    return None


def extrair_texto_visual(path, backup_path):
    total_paginas = _contar_paginas(path)
    if total_paginas is None:
        print(f"  ❌ Não foi possível determinar o número de páginas. PDF pode estar corrompido ou protegido.")
        print(f"     Tente: abrir o PDF no navegador, exportar como PDF novamente e substituir o arquivo.")
        return []

    resultado = []
    paginas_feitas = set()
    paginas_ocr_restantes = 0

    parcial_path = backup_path.with_suffix(".parcial.json")
    if parcial_path.exists():
        with open(parcial_path, encoding="utf-8") as f:
            resultado = json.load(f)
            paginas_feitas = {r["pagina"] for r in resultado}
        print(f"  Retomando ({len(paginas_feitas)} páginas já feitas)")

    pagina = 1
    while True:
        if pagina in paginas_feitas:
            pagina += 1
            continue

        try:
            imagens = convert_from_path(path, dpi=150, first_page=pagina, last_page=pagina)
        except PDFPageCountError:
            break
        if not imagens:
            break

        img = imagens[0]

        if paginas_ocr_restantes > 0:
            texto_bruto = pytesseract.image_to_string(img, lang="por+eng")
            paginas_ocr_restantes -= 1
            fonte = "OCR"
            if paginas_ocr_restantes == 0:
                print(f"  🔁 Voltando ao Gemini na próxima página...")
        else:
            for tentativa in range(1, 4):
                try:
                    response = model.generate_content([PROMPT, img])
                    try:
                        texto_bruto = response.text
                        fonte = "Gemini"
                    except ValueError:
                        print(f"  ⚠️  Página {pagina} bloqueada, alternando para OCR ({MAX_PAGINAS_OCR} págs)...")
                        texto_bruto = pytesseract.image_to_string(img, lang="por+eng")
                        paginas_ocr_restantes = MAX_PAGINAS_OCR - 1
                        fonte = "OCR"
                    break
                except Exception as e:
                    if tentativa < 3:
                        espera = 10 * tentativa
                        print(f"  ⏳ Erro (tentativa {tentativa}/3), aguardando {espera}s...")
                        time.sleep(espera)
                    else:
                        print(f"  ❌ Falha após 3 tentativas, usando OCR...")
                        texto_bruto = pytesseract.image_to_string(img, lang="por+eng")
                        fonte = "OCR"

        texto = limpar_texto(texto_bruto)
        resultado.append({"pagina": pagina, "texto": texto})
        del imagens, img

        print(f"  - Página {pagina}/{total_paginas} [{fonte}] {len(texto)} chars")

        with open(parcial_path, "w", encoding="utf-8") as f:
            json.dump(resultado, f, ensure_ascii=False, indent=2)

        pagina += 1

    if parcial_path.exists():
        parcial_path.unlink()

    return resultado


# ── Pipeline principal ─────────────────────────────────────────────────────────

for categoria in sorted(Path(BOOK_DIR).iterdir()):
    if not categoria.is_dir():
        continue

    backup_categoria = Path(BACKUP_DIR) / categoria.name.lower()
    backup_categoria.mkdir(parents=True, exist_ok=True)

    print(f"\n📂 Categoria: {categoria.name}")

    for arquivo in sorted(categoria.glob("*.pdf")):
        backup_path = backup_categoria / f"{arquivo.stem}.json"

        if backup_path.exists():
            print(f"  ⏩ Pulando {arquivo.name} (já processado)")
            continue

        print(f"  🚀 Processando: {arquivo.name}")

        if pdf_e_imagetico(arquivo):
            print(f"  🖼️  PDF imagético — usando OCR visual...")
            dados_livro = extrair_texto_visual(arquivo, backup_path)
        else:
            dados_livro = extrair_texto_simples(arquivo, backup_path)

        with open(backup_path, "w", encoding="utf-8") as f:
            json.dump(dados_livro, f, ensure_ascii=False, indent=2)

        print(f"  ✅ Salvo: {backup_path}")

print("\n🏁 Concluído!")
