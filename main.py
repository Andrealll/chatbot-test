from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime
import time

from calcoli import (
    df_tutti,
    calcola_asc_mc_case,
    calcola_pianeti_da_df,
    decodifica_segni,
    genera_carta_base64
)
from metodi import interpreta_groq


app = FastAPI(title="AstroBot v13", version="13.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def root():
    return {"status": "ok", "message": "AstroBot v13 online 🪐"}


@app.post("/tema")
async def tema(request: Request):
    start = time.time()
    try:
        body = await request.json()
        citta = body.get("citta")
        data = body.get("data")
        ora_str = body.get("ora")

        if not all([citta, data, ora_str]):
            raise HTTPException(422, "Parametri 'citta', 'data' e 'ora' obbligatori.")

        # parsing flessibile
        for fmt in ("%Y-%m-%d %H:%M", "%d/%m/%Y %H:%M"):
            try:
                dt = datetime.strptime(f"{data} {ora_str}", fmt)
                break
            except ValueError:
                dt = None
        if not dt:
            raise HTTPException(422, "Formato data non riconosciuto. Usa YYYY-MM-DD o DD/MM/YYYY.")

        giorno, mese, anno = dt.day, dt.month, dt.year
        ora_i, minuti = dt.hour, dt.minute

        # === Calcoli astronomici ===
        asc = calcola_asc_mc_case(citta, anno, mese, giorno, ora_i, minuti)
        pianeti_raw = calcola_pianeti_da_df(df_tutti, giorno, mese, anno, ora_i, minuti)
        pianeti_decod = decodifica_segni(pianeti_raw)
        img_b64 = genera_carta_base64(anno, mese, giorno, ora_i, minuti, citta)

        # === Interpretazione AI ===
        interpretazione_data = interpreta_groq(
            asc=asc,
            pianeti_decod=pianeti_decod,
            meta={"citta": citta, "data": f"{anno}-{mese:02d}-{giorno:02d}", "ora": f"{ora_i:02d}:{minuti:02d}"}
        )

        elapsed = int((time.time() - start) * 1000)
        return {
            "status": "ok",
            "ascendente": asc,
            "pianeti": pianeti_decod,
            "interpretazione": interpretazione_data["interpretazione"],
            "sintesi": interpretazione_data["sintesi"],
            "image_base64": img_b64,
            "elapsed_ms": elapsed
        }

    except HTTPException as e:
        raise e
    except Exception as e:
        return {"status": "error", "message": str(e)}
