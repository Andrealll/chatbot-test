from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime
from pydantic import BaseModel
from typing import Optional
import time

from astrobot_core.calcoli import (
    df_tutti,
    calcola_asc_mc_case,
    calcola_pianeti_da_df,
    decodifica_segni,
    genera_carta_base64
)
from astrobot_core.metodi import interpreta_groq
from transiti import calcola_transiti_data_fissa


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
            raise HTTPException(status_code=422, detail="Parametri 'citta', 'data' e 'ora' obbligatori.")

        # Parsing flessibile della data (unisce data + ora)
        dt = None
        for fmt in ("%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M", "%d/%m/%Y %H:%M"):
            try:
                dt = datetime.strptime(f"{data} {ora_str}", fmt)
                break
            except ValueError:
                continue

        if not dt:
            raise HTTPException(
                status_code=422,
                detail="Formato data non riconosciuto. Usa YYYY-MM-DD o DD/MM/YYYY con ora HH:MM."
            )

        giorno, mese, anno = dt.day, dt.month, dt.year
        ora_i, minuti = dt.hour, dt.minute

        # Calcoli astronomici
        asc = calcola_asc_mc_case(citta, anno, mese, giorno, ora_i, minuti)
        pianeti_raw = calcola_pianeti_da_df(df_tutti, giorno, mese, anno, ora_i, minuti)
        pianeti_decod = decodifica_segni(pianeti_raw)
        img_b64 = genera_carta_base64(anno, mese, giorno, ora_i, minuti, citta)

        # Interpretazione AI
        interpretazione_data = interpreta_groq(
            asc=asc,
            pianeti_decod=pianeti_decod,
            meta={
                "citta": citta,
                "data": f"{anno}-{mese:02d}-{giorno:02d}",
                "ora": f"{ora_i:02d}:{minuti:02d}"
            }
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

    except HTTPException:
        raise
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.get("/status")
async def status_check():
    """
    Test diagnostico: verifica disponibilità di servizi e dipendenze.
    """
    from astrobot_core.calcoli import df_tutti, calcola_pianeti_da_df, geocodifica_citta_con_fuso
    from astrobot_core.metodi import call_ai_model

    results = {}
    try:
        # Effemeridi
        if df_tutti is None or df_tutti.empty:
            results["effemeridi"] = "❌ non caricate"
        else:
            results["effemeridi"] = f"✅ {len(df_tutti)} righe caricate"

        # Calcolo rapido pianeti
        try:
            pianeti = calcola_pianeti_da_df(df_tutti, 19, 7, 1986, 8, 50)
            sole = pianeti.get("Sole", {})
            results["calcolo_pianeti"] = f"✅ Sole {sole}" if sole else "⚠️ dati parziali"
        except Exception as e:
            results["calcolo_pianeti"] = f"❌ errore: {e}"

        # Geocoding
        try:
            info = geocodifica_citta_con_fuso("Napoli", 1986, 7, 19, 8, 50)
            results["geocodifica"] = f"✅ {info['lat']}, {info['lon']} ({info['timezone']})"
        except Exception as e:
            results["geocodifica"] = f"❌ errore: {e}"

        # Test AI Groq
        try:
            import os
            if os.environ.get("GROQ_API_KEY"):
                response = call_ai_model(
                    [{"role": "user", "content": "Scrivi 'ok'."}],
                    max_tokens=10
                )
                if "ok" in response.lower():
                    results["AI_Groq"] = "✅ risposta corretta"
                else:
                    results["AI_Groq"] = f"⚠️ risposta inattesa: {response}"
            else:
                results["AI_Groq"] = "⚠️ GROQ_API_KEY non impostata"
        except Exception as e:
            results["AI_Groq"] = f"❌ errore: {e}"

        return {"status": "ok", "message": "Self-test completato", "results": results}

    except Exception as e:
        return {"status": "error", "message": str(e), "results": results}


# --------- Transiti: modelli e rotte ---------

class TransitiReq(BaseModel):
    giorno: int
    mese: int
    anno: int
    ora: int = 12
    minuti: int = 0
    citta: Optional[str] = None


@app.post("/transiti", tags=["Transiti"], summary="Calcolo transiti su data fissa (POST)")
def transiti_post(req: TransitiReq):
    return calcola_transiti_data_fissa(
        giorno=req.giorno,
        mese=req.mese,
        anno=req.anno,
        ora=req.ora,
        minuti=req.minuti,
        citta=req.citta
    )


@app.get("/transiti", tags=["Transiti"], summary="Calcolo transiti su data fissa (GET)")
def transiti_get(
    giorno: int,
    mese: int,
    anno: int,
    ora: int = 12,
    minuti: int = 0,
    citta: Optional[str] = None
):
    return calcola_transiti_data_fissa(
        giorno=giorno,
        mese=mese,
        anno=anno,
        ora=ora,
        minuti=minuti,
        citta=citta
    )



from fastapi import Body, HTTPException
from datetime import datetime

# from sinastria import sinastria

@app.post("/sinastria")
async def api_sinastria(payload: dict = Body(...)):
    """
    Esempio payload:
    {
      "A": {"data": "1986-07-19", "ora": "10:30", "lat": 45.4642, "lon": 9.19, "fuso_orario": 1.0},
      "B": {"data": "1990-01-01", "ora": "15:00", "lat": 40.8518, "lon": 14.2681, "fuso_orario": 1.0},
      "include_node": true,
      "include_lilith": true,
      "sistema_case": "equal"
    }
    """
    try:
        A = payload.get("A", {})
        B = payload.get("B", {})

        def parse_side(side):
            data = side.get("data")
            ora = side.get("ora", "00:00") or "00:00"
            lat = float(side["lat"])
            lon = float(side["lon"])
            fuso = float(side.get("fuso_orario", 0.0))
            dt = datetime.strptime(f"{data} {ora}", "%Y-%m-%d %H:%M")
            return dt, lat, lon, fuso

        dtA, latA, lonA, fusoA = parse_side(A)
        dtB, latB, lonB, fusoB = parse_side(B)

        include_node = bool(payload.get("include_node", True))
        include_lilith = bool(payload.get("include_lilith", True))
        sistema_case = payload.get("sistema_case", "equal")

        result = sinastria(
            dtA, latA, lonA, fusoA,
            dtB, latB, lonB, fusoB,
            include_node, include_lilith, sistema_case
        )
        return {"status": "ok", "result": result}

    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Errore input/processing: {e}" )

