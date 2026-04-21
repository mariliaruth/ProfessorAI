# processar_biblioteca_openai.py
# Versão alternativa usando OpenAI GPT-4o Vision no lugar do Gemini.
#
# Diferenças em relação ao processar_biblioteca.py (Gemini):
#   - Gemini aceita objeto PIL diretamente na chamada
#   - OpenAI exige a imagem convertida para base64 dentro do payload JSON
#   - Modelo: gpt-4o-mini (mais barato) ou gpt-4o (mais preciso)
#   - Custo vision: ~$0.002–$0.005 por página (vs ~$0.001 no Gemini)
#
# Execução:
#   .venv/bin/python processar_biblioteca_openai.py

import os
import re
import io
import json
import base64
import random
import time
from pathlib import Path
from pdf2image import convert_from_path
from pdf2image.exceptions import PDFPageCountError
import pytesseract
from langchain_community.document_loaders import PyPDFLoader
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

#ROOT_DIR = Path(__file__).resolve().parent.parent
ROOT_DIR = Path().resolve()
while not (ROOT_DIR / "Livros_base").exists():
    ROOT_DIR = ROOT_DIR.parent
    
BOOK_DIR   = ROOT_DIR / "Livros_base"
BACKUP_DIR = ROOT_DIR / "backup_textos"
MAX_PAGINAS_OCR = 5
MODEL_VISION    = "gpt-4o-mini"   # troque por "gpt-4o" para maior precisão

PROMPT = """Transcreva o texto desta página exatamente como está escrito.
- Mantenha todos os termos técnicos originais.
- NÃO escreva cabeçalhos, introduções ou observações sobre a página.
- NÃO diga "o idioma é X" nem "o texto diz".
- Se houver uma figura, diagrama ou ilustração: descreva o CONTEÚDO SIMBÓLICO
  (ex: quais planetas aparecem, quais signos, quais símbolos, o que a carta de
  Tarot representa). NÃO descreva o layout visual (posição na página, formato
  geométrico, cores, tamanho).
- Comece diretamente pelo conteúdo do texto."""


# ── Limpeza de artefatos (idêntica ao processar_biblioteca.py) ────────────────

_ARTEFATOS = [
    r"(?im)^\s*\*{0,2}Identificação do Idioma[:\*]*.*$",
    r"(?im)^\s*\*{0,2}O idioma d[ae]sta página é[^\.]*\.\s*$",
    r"(?im)^\s*\*{0,2}Transcrição Fiel do Texto[:\*]*.*$",
    r"(?im)^\s*\*{0,2}Descrição Detalhada dos Diagramas[:/\*]*.*$",
    r"(?im)^\s*\*{0,2}Símbolo[s]?[:\*].*$",
    r"(?im)^\s*\*{0,2}Notas Adicionais[:\*].*$",
    r"(?m)^\s*\d{1,4}\s*$",
]


def limpar_texto(texto: str) -> str:
    for padrao in _ARTEFATOS:
        texto = re.sub(padrao, "", texto)
    texto = re.sub(r" {2,}", " ", texto)
    texto = re.sub(r"\n{3,}", "\n\n", texto)
    return texto.strip()


# ── Conversão de imagem PIL → base64 (necessário para OpenAI) ────────────────

def pil_para_base64(img) -> str:
    """Converte imagem PIL para string base64 PNG — formato exigido pela OpenAI."""
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("utf-8")


# ── Chamada à API OpenAI Vision ───────────────────────────────────────────────

def extrair_texto_com_openai(img) -> str:
    """
    Envia uma imagem PIL para o GPT-4o Vision e retorna o texto extraído.

    Estrutura do payload OpenAI (diferente do Gemini):
      - messages[0].content é uma lista com dois itens:
          1. {"type": "text", "text": PROMPT}
          2. {"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}}
    """
    img_b64 = pil_para_base64(img)
    response = client.chat.completions.create(
        model=MODEL_VISION,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": PROMPT},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/png;base64,{img_b64}",
                            "detail": "high",   # "low" é mais barato mas menos preciso
                        },
                    },
                ],
            }
        ],
        max_tokens=2048,
    )
    return response.choices[0].message.content or ""


# ── Detecção de PDF imagético ─────────────────────────────────────────────────

def pdf_e_imagetico(path, n_paginas=5, min_chars_por_pagina=100):
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


# ── Extração de PDF nativo ────────────────────────────────────────────────────

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


# ── Extração de PDF imagético (OpenAI Vision + fallback OCR) ─────────────────

def _contar_paginas(path) -> int | None:
    """Tenta contar as páginas do PDF por dois métodos diferentes."""
    try:
        from pdf2image import pdfinfo_from_path
        return pdfinfo_from_path(path)["Pages"]
    except Exception:
        pass
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
            # Fallback local quando a OpenAI bloqueia por copyright
            texto_bruto = pytesseract.image_to_string(img, lang="por+eng")
            paginas_ocr_restantes -= 1
            fonte = "OCR"
            if paginas_ocr_restantes == 0:
                print(f"  🔁 Voltando à OpenAI na próxima página...")
        else:
            for tentativa in range(1, 4):
                try:
                    texto_bruto = extrair_texto_com_openai(img)
                    fonte = f"OpenAI {MODEL_VISION}"
                    break
                except Exception as e:
                    err = str(e).lower()
                    # OpenAI recusa conteúdo por policy (equivalente ao bloqueio de copyright do Gemini)
                    if "content_policy" in err or "refused" in err:
                        print(f"  ⚠️  Página {pagina} recusada pela OpenAI, usando OCR ({MAX_PAGINAS_OCR} págs)...")
                        texto_bruto = pytesseract.image_to_string(img, lang="por+eng")
                        paginas_ocr_restantes = MAX_PAGINAS_OCR - 1
                        fonte = "OCR"
                        break
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


# ── Pipeline principal ────────────────────────────────────────────────────────

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
            print(f"  🖼️  PDF imagético — usando OpenAI Vision...")
            dados_livro = extrair_texto_visual(arquivo, backup_path)
        else:
            dados_livro = extrair_texto_simples(arquivo, backup_path)

        with open(backup_path, "w", encoding="utf-8") as f:
            json.dump(dados_livro, f, ensure_ascii=False, indent=2)

        print(f"  ✅ Salvo: {backup_path}")

print("\n🏁 Concluído!")
