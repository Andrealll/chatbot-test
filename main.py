from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from openai import OpenAI
import os, time
from calcoli import calcola_pianeti_da_df, df_tutti

# -------------------------------------------------------------
# CONFIGURAZIONE
# -------------------------------------------------------------
VERSION = "3.2"
app = FastAPI(title=f"Chatbot Backend Groq v{VERSION}")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 🔒 restringi in produzione
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 🧠 Client Groq - compatibile OpenAI
client = OpenAI(
    api_key=os.environ.get("GROQ_API_KEY"),
    base_url="https://api.groq.com/openai/v1"
)

# -------------------------------------------------------------
@app.get("/")
def home():
    return {
        "status": "ok",
        "message": f"Backend Groq v{VERSION} attivo (valori normalizzati)",
    }

# -------------------------------------------------------------
@app.post("/run")
async def run(request: Request):
    data = await request.json()
    giorno, mese, anno = int(data["giorno"]), int(data["mese"]), int(data["anno"])

    # Calcolo pianeti (usa vettore senza segni)
    _, valori_norm = calcola_pianeti_da_df(df_tutti, giorno, mese, anno)
    testo_pianeti = "\n".join([f"{k}: {v:.2f}°" for k, v in valori_norm.items()])

    prompt = f"""
    Data: {giorno}/{mese}/{anno}
    Pianeti (valori normalizzati):
    {testo_pianeti}

    Genera una breve interpretazione astrologica in italiano, tono professionale e positivo.
    """

    # ---------------------------------------------------------
    # Chiamata Groq (Llama 3.3 con fallback automatico)
    # ---------------------------------------------------------
    t0 = time.time()
    messages = [
        {"role": "system", "content": "Sei un esperto astrologo che scrive con chiarezza e ispirazione."},
        {"role": "user", "content": prompt}
    ]

    try:
        # Modello principale
        resp = client.chat.completions.create(
            model="llama-3.3-70b-versatile",  # ✅ modello attivo su Groq
            messages=messages,
            temperature=0.7,
            max_tokens=500
        )
        testo_groq = resp.choices[0].message.content
        model_used = resp.model
    except Exception as e1:
        # Fallback su modello più leggero
        try:
            resp = client.chat.completions.create(
                model="llama-3.1-8b-instant",
                messages=messages,
                temperature=0.7,
                max_tokens=500
            )
            testo_groq = resp.choices[0].message.content
            model_used = resp.model
        except Exception as e2:
            testo_groq = f"Errore Groq su entrambi i modelli: {e2}"
            model_used = "none"

    elapsed = int((time.time() - t0) * 1000)

    return {
        "status": "ok",
        "model_used": model_used,
        "giorno": giorno,
        "mese": mese,
        "anno": anno,
        "valori_raw": valori_norm,  # mantiene stesso nome per compatibilità
        "interpretazione": testo_groq,
        "response_time_ms": elapsed
    }
