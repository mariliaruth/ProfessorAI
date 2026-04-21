#professor.py
import os
from typing import TypedDict
from dotenv import load_dotenv
from langgraph.graph import StateGraph, END
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import SystemMessage, HumanMessage

# Importações dos seus módulos internos
from core.rag import buscar_contexto
from utils.catalogo_livros import fontes_para_markdown_abnt  # Mantenha o padrão que você definiu

load_dotenv()
os.environ["GOOGLE_API_KEY"] = os.getenv("GEMINI_API_KEY", "")

# --- DEFINIÇÃO DO ESTADO ---
class ProfessorState(TypedDict):
    pergunta: str
    tema: str
    pergunta_otimizada: str
    contexto: str
    resposta: str

# --- COMPONENTES DE LÓGICA (NÓS) ---

def reescrever_pergunta(pergunta_original, tema):
    llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature=0.1)
    prompt = (
        f"Você é um especialista em {tema}. Reescreva a pergunta do usuário para incluir "
        "termos técnicos e conceitos relacionados para busca em biblioteca acadêmica. "
        "Retorne APENAS a pergunta reescrita."
    )
    mensagens = [SystemMessage(content=prompt), HumanMessage(content=pergunta_original)]
    return llm.invoke(mensagens).content

# --- NÓS DO GRAFO (FUNÇÕES DE TRANSIÇÃO) ---

def nodo_otimizador(state: ProfessorState):
    print(f"🧠 Otimizando pergunta para {state['tema']}...")
    otimizada = reescrever_pergunta(state['pergunta'], state['tema'])
    return {"pergunta_otimizada": otimizada}

def nodo_recuperador(state: ProfessorState):
    print(f"🔍 Recuperando contexto para: {state['pergunta_otimizada']}...")
    # k=5 garante uma boa profundidade de busca
    ctx = buscar_contexto(state['pergunta_otimizada'], categoria=state['tema'], k=5)
    return {"contexto": ctx}

def nodo_gerador(state: ProfessorState):
    print("✍️ Gerando resposta final...")
    if not state['contexto']:
        return {"resposta": "Sinto muito, não encontrei referências bibliográficas para este tema."}

    llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature=0.2)
    prompt_sistema = (
        "Você é um professor acadêmico especialista. Responda usando APENAS o contexto fornecido. "
        "É OBRIGATÓRIO manter as citações no formato [fonte, p.X] ao longo do texto."
    )
    
    mensagens = [
        SystemMessage(content=prompt_sistema),
        HumanMessage(content=f"Contexto:\n{state['contexto']}\n\nPergunta: {state['pergunta']}")
    ]
    
    resposta_llm = llm.invoke(mensagens).content
    
    # 4. Formata a Bibliografia usando seu motor ABNT
    bibliografia = fontes_para_markdown_abnt(state['contexto'])
    
    # Combina a resposta com a bibliografia formatada
    return {"resposta": f"{resposta_llm}\n\n{bibliografia}"}

# --- ORQUESTRAÇÃO DO FLUXO ---

workflow = StateGraph(ProfessorState)

workflow.add_node("otimizar", nodo_otimizador)
workflow.add_node("recuperar", nodo_recuperador)
workflow.add_node("responder", nodo_gerador)

workflow.set_entry_point("otimizar")
workflow.add_edge("otimizar", "recuperar")
workflow.add_edge("recuperar", "responder")
workflow.add_edge("responder", END)

# Compilação do Agente
professor_agent = workflow.compile()

# Função auxiliar para manter a compatibilidade com seus testes antigos
def perguntar_ao_professor(pergunta, tema):
    inputs = {"pergunta": pergunta, "tema": tema}
    resultado = professor_agent.invoke(inputs)
    return resultado["resposta"]