# 🎓 ProfessorAI — RAG com Citações Acadêmicas (ABNT)

> Transforme PDFs e livros acadêmicos em um assistente inteligente que responde com base em fontes reais — com citações em ABNT.

---

## 💡 O que este projeto faz?

Modelos de linguagem tradicionais geram respostas genéricas, não citam fontes e podem alucinar informações. O **ProfessorAI** resolve isso.

Ele utiliza **RAG (Retrieval-Augmented Generation)** orquestrado via **LangGraph** para:

- buscar trechos relevantes na sua biblioteca de PDFs
- reescrever perguntas para maximizar a recuperação semântica (*query expansion*)
- gerar respostas fundamentadas com **citações automáticas no padrão ABNT**

O sistema adota a persona de um **Professor Acadêmico**: tom didático, rigor técnico e respostas limitadas estritamente ao conhecimento da sua biblioteca curada.

---

## 🧪 Exemplo de uso

**Pergunta:**
> Qual a importância da tradição oral na história africana?

**Resposta:**
> A tradição oral desempenha papel fundamental na preservação da memória coletiva e na transmissão de conhecimentos entre gerações. Ao contrário das fontes escritas, ela carrega dimensões simbólicas e culturais que documentos formais frequentemente omitem.
>
> *(UNESCO; MEC; UFSCar, 2010, p. 45)*

---

## 🧠 Arquitetura

```
PDF
 └─► OCR / Extração de texto (via OpenAI, Gemini ou OCR local)
      └─► Limpeza e normalização (JSON estruturado)
           └─► Embeddings (text-embedding-3-small)
                └─► ChromaDB (banco vetorial)
                     └─► LangGraph
                          ├─► Query Expansion (reescrita da pergunta)
                          ├─► Recuperação semântica
                          └─► Geração de resposta com citação ABNT
```

---

## ⚙️ Pipeline de Dados

O processamento deve seguir esta ordem para que o Professor tenha fontes para consultar:

### 1. Extração e OCR
Converte PDFs em texto limpo no formato JSON. Escolha o método conforme sua necessidade:

**OCR local** — sem custo de API
```bash
python ingestion/processar_biblioteca_ocr_local.py
```

**Google Gemini** — alternativa via API Google, com fallback para processar_biblioteca_ocr_local.py caso haja erro de copyright
```bash
python ingestion/processar_biblioteca_gemini.py
```

**OpenAI GPT-4o** — alternativa via API OpenAI, com fallback para processar_biblioteca_ocr_local.py caso haja erro de copyright
```bash
python ingestion/processar_biblioteca_openai.py
```

### 2. Indexação Vetorial
Carrega os textos processados no ChromaDB.
```bash
python ingestion/popular_db.py
```

### 3. Catálogo de Metadados
Gera o catálogo de referências para as citações ABNT.
```bash
python ingestion/gerar_catalogo.py
```

---

## ▶️ Como rodar

```bash
git clone <repo>
cd professorai
pip install -r requirements.txt
cp .env.example .env
```

Configure as chaves no `.env`:
```
OPENAI_API_KEY=...
GOOGLE_API_KEY=...
```

Execute o pipeline acima e depois interaja com o agente:

```python
from core.professor import perguntar_ao_professor

resposta = perguntar_ao_professor(
    "Qual a importância da tradição oral?",
    tema="historia"
)
print(resposta)
```

---

## 🧰 Tecnologias

| Camada | Tecnologia |
|---|---|
| Orquestração | LangChain / LangGraph |
| LLM principal | Google Gemini 2.5 Flash |
| OCR / Visão | OpenAI GPT-4o |
| Embeddings | OpenAI `text-embedding-3-small` |
| Banco vetorial | ChromaDB |
| Linguagem | Python 3.12+ |

---

## 📖 Dataset de Exemplo

Para fins de demonstração e validação do pipeline, o projeto utiliza:

**Obra:** *História Geral da África, Vol. I: Metodologia e pré-história da África*  
**Organização:** UNESCO / MEC / UFSCar (2010)  
**Licença:** Acesso aberto — [Portal Domínio Público (MEC)](https://dominiopublico.mec.gov.br/download/texto/ue000318.pdf)

Escolhida pela complexidade estrutural: texto denso, notas de rodapé e terminologia científica especializada — ideal para estressar o pipeline de OCR e a fidelidade das citações.

---

## 🎯 Casos de Uso

- **Estudantes** → respostas com base em fontes verificadas, prontas para citar
- **Pesquisadores** → apoio à escrita acadêmica com rastreabilidade bibliográfica
- **Criadores de conteúdo** → geração de conteúdo fundamentado em referências reais
- **Plataformas educacionais** → tutores inteligentes com corpus curado

---

## ⚠️ Limitações

- A qualidade das respostas depende diretamente da qualidade do OCR
- O Professor só sabe o que está na biblioteca carregada — sem conhecimento externo
- Documentos muito fragmentados podem perder coerência na recuperação semântica

---

## 📂 Estrutura do Projeto

```
core/           # lógica principal: RAG, grafo LangGraph, agente Professor
ingestion/      # pipeline ETL: OCR, vetorização, catálogo ABNT
utils/          # motor de formatação bibliográfica e helpers
notebooks/      # exploração, testes e validação de resultados
data/           # PDFs de entrada (ignorado no git)
db_knowledge/   # banco vetorial ChromaDB (ignorado no git)
```

---

## 📄 Licença

Distribuído sob a licença **MIT**. Veja o arquivo `LICENSE` para o texto completo.
