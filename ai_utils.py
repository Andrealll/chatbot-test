# ai_utils.py — AstroBot v9 (Groq live)
import os
from typing import List, Dict, Optional, Tuple
from groq import Groq

# ======================================================
# CONFIGURAZIONE BASE
# ======================================================

GROQ_API_KEY = os.getenv("GROQ_API_KEY") or "INSERISCI-LA-TUA-CHIAVE"
DEFAULT_MODEL = os.getenv("AI_MODEL", "mixtral-8x7b-32768")
DEFAULT_TEMPERATURE = float(os.getenv("AI_TEMPERATURE", "0.3"))
DEFAULT_MAX_TOKENS = int(os.getenv("AI_MAX_TOKENS", "1000"))
DEFAULT_PROVIDER = "groq"

# Inizializza client
client_groq = Groq(api_key=GROQ_API_KEY)

# ======================================================
# CHIAMATA AL MODELLO AI
# ======================================================

def call_ai_model(
    messages: List[Dict[str, str]],
    model: str = DEFAULT_MODEL,
    temperature: float = DEFAULT_TEMPERATURE,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    provider: str = DEFAULT_PROVIDER
) -> str:
    """
    Esegue la chiamata al modello Groq (mixtral-8x7b o altri).
    """
    try:
        if provider == "groq":
            response = client_groq.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens
            )
            return response.choices[0].message.content.strip()

        else:
            raise ValueError(f"Provider non supportato: {provider}")

    except Exception as e:
        return f"[Errore AI] {str(e)}"


# ======================================================
# MOCK RAG (senza DB)
# ======================================================

def retrieve_knowledge(query: str, top_k: int = 3) -> List[Tuple[str, float]]:
    """
    Placeholder per futura integrazione con FAISS / Chroma.
    Restituisce risposte simulate, ma puoi già sostituirle con testi reali.
    """
    return [
        ("Il Sole rappresenta la vitalità e la volontà di espressione individuale.", 0.91),
        ("La Luna riflette la sfera emotiva e il bisogno di sicurezza.", 0.87),
        ("Marte indica energia, impulso e iniziativa personale.", 0.84)
    ]


def export_to_chunks(texts: List[str], chunk_size: int = 500) -> List[str]:
    """
    Divide testi lunghi in blocchi per futura indicizzazione RAG.
    """
    chunks = []
    for t in texts:
        t = t.strip()
        for i in range(0, len(t), chunk_size):
            chunks.append(t[i:i+chunk_size])
    return chunks


def generate_with_rag(domanda: str) -> str:
    docs = retrieve_knowledge(domanda)
    context = "\n".join([f"- {d[0]} (sim={d[1]:.2f})" for d in docs])
    system = "Sei un astrologo AI: rispondi solo in base al contesto fornito."
    user = f"CONTESTO:\n{context}\n\nDOMANDA:\n{domanda}"
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    return call_ai_model(messages)
