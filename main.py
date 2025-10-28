from fastapi import FastAPI, Request, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
import os, json, time
from pathlib import Path
from openai import OpenAI
from calcoli import calcola_pianeti_da_df, df_tutti

# -------------------------------------------------------------
# CONFIGURAZIONE BASE
# -------------------------------------------------------------
VERSION = "2.4"
app = FastAPI(title=f"Chatbot Backend GPT-3.5-only v{VERSION}")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 🔒 restringi in produzione
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

CACHE_FILE = Path("/tmp/cache_gpt.json")
STATS_FILE = Path("/tmp/stats_gpt.json")
cache, stats = {}, {"total_requests": 0, "cache_hits": 0, "avg_response_ms": 0.0}

# -------------------------------------------------------------
# FUNZIONI DI SUPPORTO
# -------------------------------------------------------------
def load_cache():
    global cache
    if CACHE_FILE.exists():
        try:
            cache.update(json.load(open(CACHE_FILE)))
        except Exception:
            pass

def save_cache():
    try:
        json.dump(cache, open(CACHE_FILE, "w"))
    except Exception:
        pass

def load_stats():
    global stats
    if STATS_FILE.exists():
        try:
            stats.update(json.load(open(STATS_FILE)))
        except Exception:
            pass

def save_stats():
    try:
        json.dump(stats, open(STATS_FILE, "w"))
    except Exception:
        pass

def safe_int(v, d):
    try:
        return int(v)
    except Exception:
        return d

load_cache(); load_stats()

# -------------------------------------------------------------
@app.get("/")
def home():
    return {
        "status": "ok",
        "message": f"Backend GPT-3.5-only v{VERSION} operativo",
        "cached_entries": len(cache),
        "stats": stats
    }

# -------------------------------------------------------------
@app.post("/run")
async def run(request: Request, authorization: str | None = Header(None)):
    API_TOKEN = os.environ.get("API_TOKEN")
    if API_TOKEN and authorization != f"Bearer {API_TOKEN}":
        raise HTTPException(status_code=401, detail="Unauthorized")

    data = await request.json()
    giorno, mese, anno = safe_int(data.get("giorno"),1), safe_int(data.get("mese"),1), safe_int(data.get("anno"),2000)
    key = f"{giorno}-{mese}-{anno}"
    stats["total_requests"] += 1

    # Cache
    if key in cache:
        stats["cache_hits"] += 1
        save_stats()
        return {"status":"ok","cached":True,**cache[key]}

    # Calcolo pianeti
    try:
        valori_raw, _ = calcola_pianeti_da_df(df_tutti, giorno, mese, anno)
    except Exception as e:
        return {"status":"error","message":str(e)}

    testo_pianeti = "\n".join([f"{k}: {v:.2f}°" for k,v in valori_raw.items()])
    prompt = f"Oggi è il {giorno}/{mese}/{anno}.\n{testo_pianeti}\nScrivi una breve sintesi interpretativa in italiano, tono professionale e positivo."

    # GPT-3.5-turbo (unico modello)
    t0 = time.time()
    try:
        resp = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "Sei un esperto di astrologia che spiega con chiarezza e ispirazione."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7,
            max_tokens=300
        )
        testo_gpt = resp.choices[0].message.content
    except Exception as e:
        testo_gpt = f"Errore GPT: {e}"

    elapsed = int((time.time() - t0)*1000)
    stats["avg_response_ms"] = round((stats["avg_response_ms"] + elapsed)/2, 1)
    save_stats()

    cache[key] = {
        "cached": False,
        "model_used": "gpt-3.5-turbo",
        "giorno": giorno, "mese": mese, "anno": anno,
        "valori_raw": valori_raw,
        "interpretazione": testo_gpt,
        "response_time_ms": elapsed
    }
    save_cache()

    return cache[key]

# -------------------------------------------------------------
@app.get("/stats")
def get_stats():
    return {"ok": True, "stats": stats, "cached_entries": len(cache)}
