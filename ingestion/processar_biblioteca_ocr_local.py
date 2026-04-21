# processar_ocr_local.py
# OCR local com pytesseract — sem restrições de copyright
import os
import json
from pathlib import Path
from pdf2image import convert_from_path
from pdf2image.exceptions import PDFPageCountError
import pytesseract
from dotenv import load_dotenv

load_dotenv()

# Livros a processar: informe o caminho do PDF e o idioma predominante
# Idiomas disponíveis: por (português), eng (inglês), spa (espanhol)
LIVROS = [
    {"pdf": "../Livros_base/amostra_aberta/Metodologia_e_pre-historia_da_africa.pdf", "lang": "por"},
]

BACKUP_DIR = "./backup_textos"


def extrair_texto_ocr(path, backup_path, lang="por"):
    """Processa o PDF página por página com OCR local (pytesseract)."""
    resultado = []
    paginas_feitas = set()

    parcial_path = backup_path.with_suffix(".parcial.json")
    if parcial_path.exists():
        with open(parcial_path, encoding="utf-8") as f:
            resultado = json.load(f)
            paginas_feitas = {r["pagina"] for r in resultado}
        print(f"  Retomando do progresso anterior ({len(paginas_feitas)} páginas já feitas)")

    pagina = 1
    while True:
        if pagina in paginas_feitas:
            pagina += 1
            continue

        try:
            imagens = convert_from_path(
                path,
                dpi=300,           # OCR local precisa de resolução maior
                first_page=pagina,
                last_page=pagina,
            )
        except PDFPageCountError:
            break

        if not imagens:
            break

        img = imagens[0]
        texto = pytesseract.image_to_string(img, lang=lang)
        resultado.append({"pagina": pagina, "texto": texto.strip()})

        del imagens, img

        print(f"  - Página {pagina} ok")

        with open(parcial_path, "w", encoding="utf-8") as f:
            json.dump(resultado, f, ensure_ascii=False, indent=2)

        pagina += 1

    if parcial_path.exists():
        parcial_path.unlink()

    return resultado


for livro in LIVROS:
    arquivo = Path(livro["pdf"])
    lang = livro["lang"]

    if not arquivo.exists():
        print(f"  ❌ Arquivo não encontrado: {arquivo}")
        continue

    categoria = arquivo.parent.name.lower()
    backup_categoria = Path(BACKUP_DIR) / categoria
    backup_categoria.mkdir(parents=True, exist_ok=True)
    backup_path = backup_categoria / f"{arquivo.stem}.json"

    if backup_path.exists():
        print(f"⏩ Pulando {arquivo.name} (já processado)")
        continue

    print(f"🚀 Processando: {arquivo.name} (idioma: {lang})")
    dados_livro = extrair_texto_ocr(arquivo, backup_path, lang)

    with open(backup_path, "w", encoding="utf-8") as f:
        json.dump(dados_livro, f, ensure_ascii=False, indent=2)

    print(f"✅ Salvo: {backup_path}")

print("\n🏁 Concluído!")
