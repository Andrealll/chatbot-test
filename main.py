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
from metodi import interpreta_groq  # nuova funzione con passaggio dati robusto

app = FastAPI(title="AstroBot v7", version="7.0")

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
    return {"status": "ok", "message": "AstroBot v7 online 🪐"}


# -------------------------------------------------
# POST /tema
# -------------------------------------------------
@app.post("/tema")
async def tema(request: Request):
    """
    Body JSON accettato:
    Nuovo formato:
    {
      "data": "1986-07-19",
      "ora": "14:30",
      "citta": "Napoli",
      "fuso": 1.0,               # opzionale
      "sistema_case": "equal",   # opzionale
      "domanda_utente": "..."    # opzionale
    }

    Legacy compatibile:
    {
      "giorno": 19, "mese": 7, "anno": 1986,
      "ora": 14, "minuti": 30,
      "citta": "Napoli",
      "domanda_utente": "..."    # opzionale
    }
    """
    start = time.time()

    try:
        body = await request.json()

        citta = body.get("citta")
        if not citta:
            raise HTTPException(status_code=422, detail="Campo 'citta' obbligatorio.")

        fuso = body.get("fuso", 0.0)
        sistema_case = body.get("sistema_case", "equal")
        domanda_utente = body.get("domanda_utente")

        # Nuovo formato
        data = body.get("data")
        ora_str = body.get("ora")

        # Legacy
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
                raise HTTPException(
                    status_code=422,
                    detail="Formato data/ora non valido. Usa YYYY-MM-DD e HH:MM."
                )
        else:
            # Legacy
            ora_i = body.get("ora")
            if not all([giorno, mese, anno]) or ora_i is None or minuti is None:
                raise HTTPException(
                    status_code=422,
                    detail="Parametri insufficienti: fornisci data/ora oppure giorno/mese/anno/ora/minuti."
                )

        # --- Calcoli base ---
        asc = calcola_asc_mc_case(citta, anno, mese, giorno, ora_i, minuti)
        pianeti_raw, _ = calcola_pianeti_da_df(df_tutti, giorno, mese, anno)
        img_b64 = genera_carta_base64(anno, mese, giorno, ora_i, minuti, citta)

        # --- Interpretazione robusta (nuova) ---
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
        # Log minimale nel payload per debug (in prod meglio loggare server-side)
        return {"status": "error", "message": str(e)}
