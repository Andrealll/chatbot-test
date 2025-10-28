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
app = FastAPI(title="Chatbot Backend GPT con fallback e monitoraggio", version="2.3")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 🔒 restringi in produzione
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Inizializza client OpenAI
client = OpenAI(
    api_key=os.environ.get("OPENAI_API_KEY"),
    organization=os.environ.get("OPENAI_ORG")
)

# Cache e statistiche
CACHE_FILE = Path("/tmp/cache_gpt.json")
STATS_FILE = Path("/tmp/stats_gpt.json")
cache = {}
stats = {"total_requests": 0, "cache_hits": 0, "models_used": {}}

# -------------------------------------------------------------
# FUNZIONI DI SUPPORTO
# -------------------------------------------------------------
def load_cache():
    global cache
    if CACHE_FILE.exists():
        try:
            cache.update(json.load(open(CACHE_FILE)))
            print(f"🗂️ Cache caricata ({len(cache)} voci).")
        except Exception as e:
            print("⚠️ Errore caricamento cache:", e)

def save_cache():
    try:
        json.dump(cache, open(CACHE_FILE, "w"))
        print("💾 Cache aggiornata.")
    except Exception as e:
        print("⚠️ Errore salvataggio cache:", e)

def load_stats():
    global stats
    if STATS_FILE.exists():
        try:
            stats.update(json.load(open(STATS_FILE)))
            print(f"📊 Stats caricate: {stats}")
        except Exception as e:
            print("⚠️ Errore caricamento stats:", e)

def save_stats():
    try:
        json.dump(stats, open(STATS_FILE, "w"))
    except Exception as e:
        print("⚠️ Errore salvataggio stats:", e)

def safe_int(value, default):
    try:
        return int(value)
    except (ValueError, TypeError):
        return default

load_cache()
load_stats()

# -------------------------------------------------------------
# ENDPOINT BASE
# -------------------------------------------------------------
@app.get("/")
def home():
    return {
        "status": "ok",
        "message": "Backend GPT multi-modello operativo",
        "cached_entries": len(cache),
        "stats": stats
    }

# -------------------------------------------------------------
# ENDPOINT PRINCIPALE
# -------------------------------------------------------------
@app.post("/run")
async def run(request: Request, authorization: str | None = Header(None)):
    API_TOKEN = os.environ.get("API_TOKEN")
    if API_TOKEN and authorization != f"Bearer {API_TOKEN}":
        raise HTTPException(status_code=401, detail="Unauthorized")

    data = await request.json()
    giorno = safe_int(data.get("giorno"), 1)
    mese = safe_int(data.get("mese"), 1)
    anno = safe_int(data.get("anno"), 2000)
    key = f"{giorno}-{mese}-{anno}"

    stats["total_requests"] += 1

    # ⚡ Cache
    if key in cache:
        stats["cache_hits"] += 1
        save_stats()
        print(f"⚡ Risposta GPT presa da cache per {key}")
        return {
            "status": "ok",
            "cached": True,
            "model_used": cache[key].get("model_used", "unknown"),
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

    # 💬 Chiamata GPT con fallback multi-modello
    candidate_models = [
        "gpt-4o-mini",     # preferito (richiede piano pagato)
        "gpt-4.1-mini",    # alternativa
        "gpt-3.5-turbo"    # sempre abilitato su Free
    ]

    testo_gpt = ""
    modello_usato = "none"
    last_err = None

    messages = [
        {"role": "system", "content": "Sei un esperto di astrologia che spiega con chiarezza e ispirazione."},
        {"role": "user", "content": prompt}
    ]

    for m in candidate_models:
        try:
            resp = client.chat.completions.create(
                model=m,
                messages=messages,
                temperature=0.7,
                max_tokens=300
            )
            testo_gpt = resp.choices[0].message.content
            modello_usato = m
            print(f"✅ Risposta ottenuta da {m}")
            break
        except Exception as e:
            print(f"⚠️ Errore con {m}: {e}")
            last_err = str(e)

    if modello_usato == "none":
        testo_gpt = f"Errore GPT su tutti i modelli candidati: {last_err}"

    # 📊 Aggiorna statistiche
    stats["models_used"][modello_usato] = stats["models_used"].get(modello_usato, 0) + 1
    save_stats()

    # 💾 Cache
    cache[key] = {
        "valori_raw": valori_raw,
        "interpretazione": testo_gpt,
        "model_used": modello_usato
    }
    save_cache()

    # 🚀 Risposta finale
    return {
        "status": "ok",
        "cached": False,
        "model_used": modello_usato,
        "giorno": giorno,
        "mese": mese,
        "anno": anno,
        "valori_raw": valori_raw,
        "interpretazione": testo_gpt
    }

# -------------------------------------------------------------
# ENDPOINT MODELS → lista dei modelli disponibili per la tua API key
# -------------------------------------------------------------
@app.get("/models")
def list_models():
    try:
        models = [m.id for m in client.models.list().data]
        return {"ok": True, "models": sorted(models)}
    except Exception as e:
        return {"ok": False, "error": str(e)}

# -------------------------------------------------------------
# ENDPOINT STATS → riepilogo utilizzo
# -------------------------------------------------------------
@app.get("/stats")
def get_stats():
    return {"ok": True, "stats": stats, "cached_entries": len(cache)}
