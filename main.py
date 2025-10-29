from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime
from typing import Optional
import time
from calcoli import (
    calcola_asc_mc_case,
    calcola_pianeti_da_df,
    genera_carta_base64,
    interpreta_groq,
    df_tutti
)

app = FastAPI(title="AstroBot v6", version="6.0")

# -------------------------------------------------
# CORS CONFIG
# -------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def root():
    return {"status": "ok", "message": "AstroBot v6 online 🪐"}


# -------------------------------------------------
# POST /tema
# -------------------------------------------------
@app.post("/tema")
async def tema(request: Request):
    """
    Endpoint principale per il calcolo del tema natale.

    Accetta JSON nel formato:
    {
      "data": "1986-07-19",
      "ora": "14:30",
      "citta": "Napoli",
      "fuso": 1.0,
      "sistema_case": "equal"
    }

    oppure il formato legacy:
    {
      "giorno": 19, "mese": 7, "anno": 1986,
      "ora": 14, "minuti": 30,
      "citta": "Napoli"
    }
    """
    start = time.time()

    try:
        body = await request.json()

        # ---- Estrai parametri base ----
        citta = body.get("citta")
        if not citta:
            raise HTTPException(status_code=422, detail="Campo 'citta' obbligatorio.")

        fuso = body.get("fuso", 0.0)
        sistema_case = body.get("sistema_case", "equal")

        # ---- Leggi formati ----
        data = body.get("data")
        ora_str = body.get("ora")

        giorno = body.get("giorno")
        mese = body.get("mese")
        anno = body.get("anno")
        minuti = body.get("minuti")

        # ---- Nuovo formato (data + ora) ----
        if data and ora_str:
            try:
                dt = datetime.strptime(f"{data} {ora_str}", "%Y-%m-%d %H:%M")
                giorno, mese, anno = dt.day, dt.month, dt.year
                ora_i, minuti = dt.hour, dt.minute
            except ValueError:
                raise HTTPException(status_code=422, detail="Formato data/ora non valido. Usa YYYY-MM-DD e HH:MM.")
        else:
            # ---- Vecchio formato compatibile ----
            ora_i = body.get("ora")
            if not all([giorno, mese, anno]) or ora_i is None or minuti is None:
                raise HTTPException(status_code=422, detail="Parametri insufficienti: fornisci data/ora oppure giorno/mese/anno/ora/minuti.")

        # ---- Calcoli astrologici ----
        asc = calcola_asc_mc_case(citta, anno, mese, giorno, ora_i, minuti)
        pianeti_raw, _ = calcola_pianeti_da_df(df_tutti, giorno, mese, anno)
        img_b64 = genera_carta_base64(anno, mese, giorno, ora_i, minuti, citta)
        interpretazione = interpreta_groq(asc, pianeti_raw)

        # ---- Output ----
        return {
            "status": "ok",
            "ascendente": asc,
            "pianeti": pianeti_raw,
            "interpretazione": interpretazione,
            "image_base64": img_b64,
            "elapsed_ms": int((time.time() - start) * 1000)
        }

    except HTTPException as e:
        raise e
    except Exception as e:
        return {"status": "error", "message": str(e)}
