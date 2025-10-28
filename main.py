from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
import time
from calcoli import calcola_asc_mc_case, calcola_pianeti_da_df, genera_carta_base64, interpreta_groq, df_tutti

app = FastAPI(title="AstroBot v3", version="3.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"],
)

@app.get("/")
def root():
    return {"status": "ok", "message": "AstroBot v3 online 🪐"}

@app.get("/tema")
def tema(
    citta: str, giorno: int, mese: int, anno: int, ora: int, minuti: int
):
    start = time.time()
    try:
        asc = calcola_asc_mc_case(citta, anno, mese, giorno, ora, minuti)
        pianeti_raw, _ = calcola_pianeti_da_df(df_tutti, giorno, mese, anno)
        img_b64 = genera_carta_base64(anno, mese, giorno, ora, minuti, citta)
        interpretazione = interpreta_groq(asc, pianeti_raw)
        return {
            "status": "ok",
            "ascendente": asc,
            "pianeti": pianeti_raw,
            "interpretazione": interpretazione,
            "image_base64": img_b64,
            "elapsed_ms": int((time.time() - start)*1000)
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}
