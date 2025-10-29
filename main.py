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

app = FastAPI(title="AstroBot v9", version="9.0")

# -------------------------------------------------
# CORS
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
    return {"status": "ok", "message": "AstroBot v9 online 🪐"}


# -------------------------------------------------
# POST /tema
# -------------------------------------------------
@app.post("/tema")
async def tema(request: Request):
    """
    Endpoint principale per il calcolo del tema natale e interpretazione.
    Accetta JSON:
    {
      "data": "1986-07-19",
      "ora": "14:30",
      "citta": "Napoli",
      "fuso": 1.0,
      "sistema_case": "equal",
      "domanda_utente": "Cosa significa il mio ascendente in Leone?"
    }
    """
    start = time.time()

    try:
        body = await request.json()

        # Campi principali
        citta = body.get("citta")
        if not citta:
            raise HTTPException(status_code=422, detail="Campo 'citta' obbligatorio.")

        fuso = body.get("fuso", 0.0)
        sistema_case = body.get("sistema_case", "equal")
        domanda_utente = body.get("domanda_utente")

        data = body.get("data")
        ora_str = body.get("ora")

        # Legacy fallback
        giorno = body.get("giorno")
        mese = body.get("mese")
        anno = body.get("anno")
        minuti = body.get("minuti")

        if data and ora_str:
            try:
                dt = datetime.strptime(f"{data} {ora_str}", "%Y-%m-%d %H:%M")
                giorno, mese, anno = dt.day, dt.month, dt.year
                ora_i, minuti = dt.hour, dt.minute
            except ValueError:
                raise HTTPException(status_code=422, detail="Formato data/ora non valido.")
        else:
            ora_i = body.get("ora")
            if not all([giorno, mese, anno]) or ora_i is None or minuti is None:
                raise HTTPException(status_code=422, detail="Parametri insufficienti.")

        # --- Calcoli astrologici ---
        asc = calcola_asc_mc_case(citta, anno, mese, giorno, ora_i, minuti)
        pianeti_raw, _ = calcola_pianeti_da_df(df_tutti, giorno, mese, anno)
        img_b64 = genera_carta_base64(anno, mese, giorno, ora_i, minuti, citta)

        # --- Interpretazione AI ---
        interpretazione = interpreta_groq(
            asc=asc,
            pianeti_raw=pianeti_raw,
            meta={
                "citta": citta,
                "data": f"{anno:04d}-{mese:02d}-{giorno:02d}",
                "ora": f"{ora_i:02d}:{minuti:02d}",
                "sistema_case": sistema_case,
                "fuso": fuso
            },
            domanda_utente=domanda_utente
        )

        elapsed = int((time.time() - start) * 1000)
        return {
            "status": "ok",
            "ascendente": asc,
            "pianeti": pianeti_raw,
            "interpretazione": interpretazione,
            "domanda_ricevuta": domanda_utente,
            "image_base64": img_b64,
            "elapsed_ms": elapsed
        }

    except HTTPException as e:
        raise e
    except Exception as e:
        return {"status": "error", "message": str(e)}
