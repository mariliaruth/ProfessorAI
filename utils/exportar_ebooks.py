"""
exportar_ebooks.py
Converte manuscritos/capitulos Markdown em EPUB e, opcionalmente, MOBI.

Este script e o caminho inverso de converter_ebooks.py:
  converter_ebooks.py  -> epub/mobi para pdf, para alimentar o RAG
  exportar_ebooks.py   -> md para epub/mobi, para publicar o texto autoral

USO
  # EPUB a partir da pasta de capitulos
  python exportar_ebooks.py projetos_livros/guia_astrologia_para_leigos/capitulos \
    --saida projetos_livros/guia_astrologia_para_leigos/ebooks/guia_astrologia_para_leigos \
    --titulo "Guia de Astrologia para Leigos" \
    --autor "Marilia Torres" \
    --ordem projetos_livros/guia_astrologia_para_leigos/ordem_capitulos.json

  # EPUB + MOBI, se o Calibre estiver instalado
  python exportar_ebooks.py projetos_livros/guia_astrologia_para_leigos/capitulos \
    --saida projetos_livros/guia_astrologia_para_leigos/ebooks/guia_astrologia_para_leigos \
    --titulo "Guia de Astrologia para Leigos" \
    --autor "Marilia Torres" \
    --ordem projetos_livros/guia_astrologia_para_leigos/ordem_capitulos.json \
    --mobi

Observacao:
  O EPUB e gerado em Python puro. Para MOBI, instale o Calibre:
    macOS: brew install calibre
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from fabrica_livros.ebooks import exportar_ebook


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Converte Markdown(s) em EPUB e opcionalmente MOBI.",
    )
    parser.add_argument("entrada", help="Arquivo .md ou pasta com capitulos .md.")
    parser.add_argument("--saida", required=True, help="Caminho base de saida, sem extensao ou com .epub/.mobi.")
    parser.add_argument("--titulo", required=True, help="Titulo do ebook.")
    parser.add_argument("--autor", default="", help="Autor(a) do ebook.")
    parser.add_argument("--idioma", default="pt-BR", help="Idioma do ebook.")
    parser.add_argument("--mobi", action="store_true", help="Tambem tenta gerar MOBI via Calibre.")
    parser.add_argument("--incluir-fatos-brutos", action="store_true", help="Inclui arquivos *_fatos_brutos.md.")
    parser.add_argument("--padrao", default="*.md", help="Padrao glob quando entrada for pasta.")
    parser.add_argument("--ordem", help="Arquivo JSON com a ordem editorial dos capitulos.")
    parser.add_argument("--sem-sumario", action="store_true", help="Nao cria a pagina visivel de Sumario.")

    args = parser.parse_args()
    formatos = ["epub", "mobi"] if args.mobi else ["epub"]

    try:
        resultado = exportar_ebook(
            entrada=Path(args.entrada),
            saida=Path(args.saida),
            titulo=args.titulo,
            autor=args.autor,
            idioma=args.idioma,
            formatos=formatos,
            incluir_fatos_brutos=args.incluir_fatos_brutos,
            padrao=args.padrao,
            sumario_visivel=not args.sem_sumario,
            ordem_path=Path(args.ordem) if args.ordem else None,
        )
    except Exception as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        raise SystemExit(1)

    print(f"EPUB gerado: {resultado['epub']}")
    if "mobi" in resultado:
        print(f"MOBI gerado: {resultado['mobi']}")
    elif "mobi_erro" in resultado:
        print(f"MOBI nao gerado: {resultado['mobi_erro']}")
    if "ordem" in resultado:
        print(f"Ordem editorial usada: {resultado['ordem']}")
    print(f"Capitulos incluidos: {len(resultado['capitulos'])}")


if __name__ == "__main__":
    main()
