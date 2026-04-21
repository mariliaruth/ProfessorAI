"""
limpar_duplicatas.py
Remove entradas duplicadas do ChromaDB sem re-gerar nenhum embedding.
Seguro rodar quantas vezes quiser — idempotente.
"""
from dotenv import load_dotenv
load_dotenv()

from langchain_openai import OpenAIEmbeddings
from langchain_chroma import Chroma

DB_DIR = "./db_knowledge"
embeddings = OpenAIEmbeddings(model="text-embedding-3-small")
db = Chroma(persist_directory=DB_DIR, embedding_function=embeddings)

# Fontes a remover do ChromaDB (cópias piores — as canônicas continuam no banco)
DUPLICATAS = [
    "Astrologia Oculta no Livro Vermelho - Carl Jung",       # cópia de: Astrologia-Oculta-no-Livro-Vermelho-Carl-Jung
    "astrologia-psicologia-e-os-4-elementos",                # cópia de: pdfcoffee.com_astrologia-psicologia-e-os-4-elementos-5-pdf-free
    "howard-sasportas-the-twelve-houses",                    # cópia de: howard-sasportas-the-houses
    "planets-in-aspect-ROBERT PELLETIER",                    # cópia de: planets-in-aspect--3-pdf-free
    "saturn-a-new-look-at-an-old-devil-",                    # cópia de: dokumen.pub_saturn-a-new-look-at-an-old-devil-...
    "the-secret-language-of-astrology-the-illustrated-key-to-unlocking-the-secrets-of-the-stars-",  # cópia de: dokumen.pub_the-secret-language-of-astrology-...
    "The Light of Egypt, Volume II Henry O. Wagner:Belle M. Wagner:Thomas H. Burgoyne",  # cópia de: lightofegypt
]

print(f"Chunks no banco antes: {db._collection.count()}\n")

total_removido = 0
for fonte in DUPLICATAS:
    resultado = db.get(where={"fonte": fonte}, include=[])
    ids = resultado["ids"]
    if ids:
        db.delete(ids=ids)
        print(f"  ✅ {len(ids):4d} chunks removidos: {fonte}")
        total_removido += len(ids)
    else:
        print(f"  ⏩ não encontrado (já limpo): {fonte}")

print(f"\nRemovidos: {total_removido} chunks")
print(f"Chunks no banco agora: {db._collection.count()}")
