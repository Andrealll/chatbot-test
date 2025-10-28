from fastapi import FastAPI, Request, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
import os
import json
from pathlib import Path
from openai import OpenAI
from calcoli import calcola_pianeti_da_df, df_tutti

# -------------------------------------------------------------
# CONFIGURAZIONE BASE
# -------------------------------------------------------------
app = FastAPI(title="Chatbot Backend GPT con fallback", version="2.1")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # restringi in produzione
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Client OpenAI (compatibile con org opzionale)
client = OpenAI(
    api_key=os.environ.get("OPENAI_API_KEY"),
    organization=os.environ.get("OPENAI_ORG")
)

# File cache locale
CACHE_FILE = Path("/tmp/cache_gpt.json")
cache = {}

# -------------------------------------------------------------
# FUNZIONI DI SUPPORTO
# -------------------------------------------------------------
def load_cache():
    global cache
    if CACHE_FILE.exists():
        try:
            with open(CACHE_FILE, "r") as f:
                cache = json.load(f)
            print(f"🗂️ Cache caricata ({len(cache)} voci).")
        except Exception as e:
            print("⚠️ Errore caricamento cache:", e)

def save_cache():
    try:
        with open(CACHE_FILE, "w") as f:
            json.dump(cache, f)
        print("💾 Cache aggiornata.")
    except Exception as e:
        print("⚠️ Errore salvataggio cache:", e)

def safe_int(value, default):
    try:
        return int(value)
    except (ValueError, TypeError):
        return default

load_cache()

# -------------------------------------------------------------
# ENDPOINT DI TEST
# -------------------------------------------------------------
@app.get("/")
def home():
    return {
        "status": "ok",
        "message": "Backend GPT + cache attivo con fallback automatico",
        "cached_entries": len(cache)
    }

# -------------------------------------------------------------
# ENDPOINT PRINCIPALE
# -------------------------------------------------------------
@app.post("/run")
async def run(request: Request, authorization: str | None = Header(None)):
    # 🔐 Token opzionale
    API_TOKEN = os.environ.get("API_TOKEN")
    if API_TOKEN and authorization != f"Bearer {API_TOKEN}":
        raise HTTPException(status_code=401, detail="Unauthorized")

    data = await request.json()
    giorno = safe_int(data.get("giorno"), 1)
    mese = safe_int(data.get("mese"), 1)
    anno = safe_int(data.get("anno"), 2000)

    key = f"{giorno}-{mese}-{anno}"

    # ⚡ Se la data è già in cache
    if key in cache:
        print(f"⚡ Risposta GPT presa da cache per {key}")
        return {
            "status": "ok",
            "cached": True,
            "giorno": giorno,
            "mese": mese,
            "anno": anno,
            "valori_raw": cache[key]["valori_raw"],
            "interpretazione": cache[key]["interpretazione"]
        }

    # 🪐 Calcolo pianeti
    try:
        valori_raw, valori_norm = calcola_pianeti_da_df(df_tutti, giorno, mese, anno)
    except Exception as e:
        return {"status": "error", "message": str(e)}

    testo_pianeti = "\n".join([f"{k}: {v:.2f}°" for k, v in valori_raw.items()])

    # ✍️ Prompt per GPT
    prompt = f"""
    Oggi è il {giorno}/{mese}/{anno}.
    Ecco le posizioni planetarie (in gradi):
    {testo_pianeti}

    Scrivi una breve sintesi interpretativa in italiano, tono professionale e positivo.
    """

    # 💬 Chiamata GPT con fallback automatico
    modello_principale = "gpt-4o-mini"
    modello_backup = "gpt-3.5-turbo"
    testo_gpt = ""

    try:
        response = client.chat.completions.create(
            model=modello_principale,
            messages=[
                {"role": "system", "content": "Sei un esperto di astrologia che spiega con chiarezza e ispirazione."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7,
            max_tokens=300
        )
        testo_gpt = response.choices[0].message.content
        print(f"✅ Risposta ottenuta da {modello_principale}")
    except Exception as e1:
        print(f"⚠️ Errore con {modello_principale}: {e1}")
        try:
            response = client.chat.completions.create(
                model=modello_backup,
                messages=[
                    {"role": "system", "content": "Sei un esperto di astrologia che spiega con chiarezza e ispirazione."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.7,
                max_tokens=300
            )
            testo_gpt = response.choices[0].message.content
            print(f"✅ Fallback su {modello_backup} riuscito")
        except Exception as e2:
            testo_gpt = f"Errore GPT su entrambi i modelli: {e2}"
            print(f"❌ GPT completamente fallito: {e2}")

    # 💾 Salvataggio in cache
    cache[key] = {
        "valori_raw": valori_raw,
        "interpretazione": testo_gpt
    }
    save_cache()

    # 🚀 Risposta finale
    return {
        "status": "ok",
        "cached": False,
        "giorno": giorno,
        "mese": mese,
        "anno": anno,
        "valori_raw": valori_raw,
        "interpretazione": testo_gpt
    }
