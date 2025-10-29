# main.py — AstroBot v10
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
from rag_utils import get_relevant_chunks  # 🔹 nuovo import

app = FastAPI(title="AstroBot v10", version="10.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def root():
    return {"status": "ok", "message": "AstroBot v10 online 🪐"}


@app.post("/tema")
async def tema(request: Request):
    """
    Endpoint principale per il calcolo del tema natale e interpretazione AI.
    """
    start = time.time()
    try:
        body = await request.json()

        # Parametri
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

        if data and ora_str:
            dt = datetime.strptime(f"{data} {ora_str}", "%Y-%m-%d %H:%M")
            giorno, mese, anno = dt.day, dt.month, dt.year
            ora_i, minuti = dt.hour, dt.minute
        else:
            ora_i = body.get("ora")
            if not all([giorno, mese, anno]) or ora_i is None or minuti is None:
                raise HTTPException(status_code=422, detail="Parametri insufficienti.")

        # --- Calcoli astrologici ---
        asc = calcola_asc_mc_case(citta, anno, mese, giorno, ora_i, minuti)
        pianeti_raw = calcola_pianeti_da_df(df_tutti, giorno, mese, anno, ora, minuti)
        img_b64 = genera_carta_base64(anno, mese, giorno, ora_i, minuti, citta)

        # --- Recupero Knowledge Base (se domanda presente) ---
        context_from_kb = ""
        if domanda_utente:
            kb_matches = get_relevant_chunks(domanda_utente)
            context_from_kb = "\n".join([f"- {m[0]} (sim={m[1]:.2f})" for m in kb_matches])

        # --- Interpretazione AI (Groq) ---
        interpretazione = interpreta_groq(
            asc=asc,
            pianeti_raw=pianeti_raw,
            meta={
                "citta": citta,
                "data": f"{anno:04d}-{mese:02d}-{giorno:02d}",
                "ora": f"{ora_i:02d}:{minuti:02d}",
                "sistema_case": sistema_case,
                "fuso": fuso,
                "context_kb": context_from_kb   # 🔹 contesto knowledge base
            },
            domanda_utente=domanda_utente
        )

        elapsed = int((time.time() - start) * 1000)
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
        return {"status": "error", "message": str(e)}
