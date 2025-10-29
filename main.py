# main.py — AstroBot v11
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime
import time

from calcoli import (
    calcola_asc_mc_case,
    calcola_pianeti_da_df,
    genera_carta_base64,
    df_tutti
)
from metodi import interpreta_groq
from rag_utils import get_relevant_chunks


# ======================================================
# CREAZIONE APP FASTAPI
# ======================================================
app = FastAPI(title="AstroBot v11", version="11.0")

# Middleware CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ======================================================
# ENDPOINT DI TEST / ROOT
# ======================================================
@app.get("/")
def root():
    return {"status": "ok", "message": "AstroBot v11 online 🪐"}


# ======================================================
# ENDPOINT PRINCIPALE: /tema
# ======================================================
@app.post("/tema")
async def tema(request: Request):
    """
    Endpoint principale per il calcolo del tema natale e interpretazione AI.
    Supporta date nei formati YYYY-MM-DD e DD/MM/YYYY.
    """
    start = time.time()
    try:
        body = await request.json()

        # --- Parametri principali ---
        citta = body.get("citta")
        if not citta:
            raise HTTPException(status_code=422, detail="Campo 'citta' obbligatorio.")

        fuso = body.get("fuso", 0.0)
        sistema_case = body.get("sistema_case", "equal")
        domanda_utente = body.get("domanda_utente")

        data = body.get("data")
        ora_str = body.get("ora")
        giorno = body.get("giorno")
        mese = body.get("mese")
        anno = body.get("anno")
        minuti = body.get("minuti")

        # --- Parsing data/ora con doppio formato ---
        if data and ora_str:
            dt = None
            for fmt in ("%Y-%m-%d %H:%M", "%d/%m/%Y %H:%M"):
                try:
                    dt = datetime.strptime(f"{data} {ora_str}", fmt)
                    break
                except ValueError:
                    continue
            if not dt:
                raise HTTPException(
                    status_code=422,
                    detail=f"Formato data non riconosciuto: {data}. Usa YYYY-MM-DD o DD/MM/YYYY."
                )
            giorno, mese, anno = dt.day, dt.month, dt.year
            ora_i, minuti = dt.hour, dt.minute
        else:
            ora_i = body.get("ora")
            if not all([giorno, mese, anno]) or ora_i is None or minuti is None:
                raise HTTPException(status_code=422, detail="Parametri insufficienti.")

        # --- Calcoli astrologici ---
        print(f"[AstroBot] Calcolo tema {giorno:02d}/{mese:02d}/{anno} {ora_i:02d}:{minuti:02d} per {citta}")
        asc = calcola_asc_mc_case(citta, anno, mese, giorno, ora_i, minuti)
        pianeti_raw = calcola_pianeti_da_df(df_tutti, giorno, mese, anno, ora_i, minuti)
        img_b64 = genera_carta_base64(anno, mese, giorno, ora_i, minuti, citta)

        print(f"[AstroBot] ASC = {asc['ASC_segno']} {asc['ASC_gradi_segno']}°, MC = {asc['MC_segno']} {asc['MC_gradi_segno']}°")
        print(f"[AstroBot] Pianeti: {', '.join(pianeti_raw.keys())}")

        # --- Recupero Knowledge Base (se domanda presente) ---
        context_from_kb = ""
        if domanda_utente:
            kb_matches = get_relevant_chunks(domanda_utente)
            context_from_kb = "\n".join([f"- {m[0]} (sim={m[1]:.2f})" for m in kb_matches])
            print(f"[AstroBot] KB context: {len(kb_matches)} matches")

        # --- Interpretazione AI (Groq) ---
        interpretazione = None
        try:
            interpretazione = interpreta_groq(
                asc=asc,
                pianeti_raw=pianeti_raw,
                meta={
                    "citta": citta,
                    "data": f"{anno:04d}-{mese:02d}-{giorno:02d}",
                    "ora": f"{ora_i:02d}:{minuti:02d}",
                    "sistema_case": sistema_case,
                    "fuso": fuso,
                    "context_kb": context_from_kb
                },
                domanda_utente=domanda_utente
            )
        except Exception as e:
            print(f"[ERRORE AI] {e}")
            interpretazione = None

        # --- Fallback automatico se l'AI non risponde ---
        if not interpretazione or "[Errore AI]" in str(interpretazione):
            interpretazione = (
                "🪐 Non è stato possibile ottenere l'interpretazione AI in questo momento. "
                "Tuttavia, il calcolo astrologico è corretto.\n"
                f"Ascendente: {asc['ASC_segno']} {asc['ASC_gradi_segno']}° — "
                f"Sole: {pianeti_raw.get('Sole', 0):.2f}°\n"
                "Riprova tra qualche minuto."
            )

        # --- Risposta finale ---
        elapsed = int((time.time() - start) * 1000)
        print(f"[AstroBot] Tempo totale: {elapsed} ms")

        return {
            "status": "ok",
            "ascendente": asc,
            "pianeti": pianeti_raw,
            "interpretazione": interpretazione,
            "context_kb": context_from_kb,
            "image_base64": img_b64,
            "elapsed_ms": elapsed
        }

    except HTTPException as e:
        raise e
    except Exception as e:
        print(f"[AstroBot] Errore generale: {e}")
        return {"status": "error", "message": str(e)}
