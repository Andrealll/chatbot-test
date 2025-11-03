from fastapi import FastAPI, Request, HTTPException, Body
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
from datetime import datetime
import time
import os

# ---- CORE: calcoli & metodi ----
from astrobot_core.calcoli import (
    df_tutti,
    calcola_asc_mc_case,
    calcola_pianeti_da_df,
    decodifica_segni,
    genera_carta_base64,
)
from astrobot_core.metodi import interpreta_groq

# ---- CORE: sinastria & transiti ----
from astrobot_core.sinastria import sinastria as calcola_sinastria
from astrobot_core.transiti import (
    calcola_transiti_data_fissa,
    transiti_su_due_date,
)

app = FastAPI(title="AstroBot v13", version="13.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # restringi se necessario
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --------------------------- ROOT ---------------------------

@app.get("/", tags=["Root"])
def root():
    return {"status": "ok", "message": "AstroBot v13 online 🪐"}

# --------------------------- TEMA ---------------------------

@app.post("/tema", tags=["Tema"], summary="Calcola tema (pianeti + ASC) e genera immagine/interpretazione")
async def tema(request: Request):
    start = time.time()
    try:
        body = await request.json()
        citta = body.get("citta")
        data = body.get("data")
        ora_str = body.get("ora")

        if not all([citta, data, ora_str]):
            raise HTTPException(status_code=422, detail="Parametri 'citta', 'data' e 'ora' obbligatori.")

        # parsing flessibile (YYYY-MM-DD / DD/MM/YYYY) + HH:MM
        dt = None
        for fmt in ("%Y-%m-%d %H:%M", "%d/%m/%Y %H:%M", "%Y/%m/%d %H:%M"):
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

        g, m, a = dt.day, dt.month, dt.year
        h, mi = dt.hour, dt.minute

        # calcoli core
        asc = calcola_asc_mc_case(citta, a, m, g, h, mi)
        pianeti_raw = calcola_pianeti_da_df(df_tutti, g, m, a, h, mi)
        pianeti_decod = decodifica_segni(pianeti_raw)
        img_b64 = genera_carta_base64(a, m, g, h, mi, citta)

        # interpretazione (Groq)
        interpretazione_data = interpreta_groq(
            asc=asc,
            pianeti_decod=pianeti_decod,
            meta={"citta": citta, "data": f"{a}-{m:02d}-{g:02d}", "ora": f"{h:02d}:{mi:02d}"}
        )

        elapsed = int((time.time() - start) * 1000)
        return {
            "status": "ok",
            "ascendente": asc,
            "pianeti": pianeti_decod,
            "interpretazione": interpretazione_data.get("interpretazione"),
            "sintesi": interpretazione_data.get("sintesi"),
            "image_base64": img_b64,
            "elapsed_ms": elapsed
        }

    except HTTPException:
        raise
    except Exception as e:
        return {"status": "error", "message": str(e)}

# --------------------------- STATUS ---------------------------

@app.get("/status", tags=["Diagnostica"], summary="Self-test servizi e dipendenze")
async def status_check():
    results = {}
    try:
        # effemeridi
        if df_tutti is None or getattr(df_tutti, "empty", True):
            results["effemeridi"] = "❌ non caricate"
        else:
            results["effemeridi"] = f"✅ {len(df_tutti)} righe caricate"

        # calcolo pianeti (smoke)
        try:
            pianeti = calcola_pianeti_da_df(df_tutti, 19, 7, 1986, 8, 50)
            sole = pianeti.get("Sole")
            results["calcolo_pianeti"] = f"✅ Sole {sole}" if sole is not None else "⚠️ dati parziali"
        except Exception as e:
            results["calcolo_pianeti"] = f"❌ errore: {e}"

        # geocoding + fuso (se disponibile nel core)
        try:
            from astrobot_core.calcoli import geocodifica_citta_con_fuso
            info = geocodifica_citta_con_fuso("Milano", 1986, 7, 19, 8, 50)
            results["geocodifica"] = f"✅ {info['lat']}, {info['lon']} ({info['timezone']})"
        except Exception as e:
            results["geocodifica"] = f"⚠️ skip/errore: {e}"

        # test AI Groq
        try:
            from astrobot_core.metodi import call_ai_model
            if os.environ.get("GROQ_API_KEY"):
                response = call_ai_model(
                    [{"role": "user", "content": "Scrivi 'ok'."}],
                    max_tokens=10
                )
                results["AI_Groq"] = "✅ risposta corretta" if isinstance(response, str) and "ok" in response.lower() else f"⚠️ risposta inattesa: {response}"
            else:
                results["AI_Groq"] = "⚠️ GROQ_API_KEY non impostata"
        except Exception as e:
            results["AI_Groq"] = f"❌ errore: {e}"

        return {"status": "ok", "message": "Self-test completato", "results": results}

    except Exception as e:
        return {"status": "error", "message": str(e), "results": results}

# --------------------------- TRANSITI (data fissa) ---------------------------

class TransitiReq(BaseModel):
    giorno: int
    mese: int
    anno: int
    ora: int = 12
    minuti: int = 0
    citta: Optional[str] = None
    include_node: bool = True
    include_lilith: bool = True

@app.post("/transiti", tags=["Transiti"], summary="Calcolo transiti su data fissa (POST)")
def transiti_post(req: TransitiReq):
    return calcola_transiti_data_fissa(
        giorno=req.giorno,
        mese=req.mese,
        anno=req.anno,
        ora=req.ora,
        minuti=req.minuti,
        citta=req.citta,
        include_node=req.include_node,
        include_lilith=req.include_lilith
    )

@app.get("/transiti", tags=["Transiti"], summary="Calcolo transiti su data fissa (GET)")
def transiti_get(
    giorno: int,
    mese: int,
    anno: int,
    ora: int = 12,
    minuti: int = 0,
    citta: Optional[str] = None,
    include_node: bool = True,
    include_lilith: bool = True
):
    return calcola_transiti_data_fissa(
        giorno=giorno,
        mese=mese,
        anno=anno,
        ora=ora,
        minuti=minuti,
        citta=citta,
        include_node=include_node,
        include_lilith=include_lilith
    )

# --------------------------- SINASTRIA ---------------------------

@app.post("/sinastria", tags=["Sinastria"], summary="Sinastria: aspetti incrociati tra due temi (pianeti + ASC)")
async def api_sinastria(payload: dict = Body(...)):
    """
    Payload:
    {
      "A": {"data": "1986-07-19", "ora": "10:30", "citta": "Milano, IT"},
      "B": {"data": "1988-11-11", "ora": "07:30", "citta": "Napoli, IT"}
    }
    """
    try:
        A = payload.get("A", {})
        B = payload.get("B", {})

        def parse_side(side):
            data = side.get("data")
            if not data:
                raise ValueError("Campo 'data' mancante (A/B)")
            ora = side.get("ora", "00:00") or "00:00"
            citta = side.get("citta")
            if not citta:
                raise ValueError("Campo 'citta' mancante (A/B)")
            dt = datetime.strptime(f"{data} {ora}", "%Y-%m-%d %H:%M")
            return dt, citta

        dtA, cittaA = parse_side(A)
        dtB, cittaB = parse_side(B)

        result = calcola_sinastria(dtA, cittaA, dtB, cittaB)  # sinastria del core (città-based)
        return {"status": "ok", "result": result}

    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Errore input/processing: {e}")

# --------------------------- TRANSITI: confronto due date ---------------------------

@app.post("/transiti-intervallo", tags=["Transiti"], summary="Confronta aspetti tra due date (persistono/entrano/escono)")
async def transiti_intervallo(payload: dict = Body(...)):
    """
    Payload:
    {
      "data_inizio": "1986-07-19", "ora_inizio": "10:30",
      "data_fine":   "1986-07-26", "ora_fine":   "12:00",
      "include_node": true, "include_lilith": true
    }
    """
    try:
        din = payload.get("data_inizio")
        dfi = payload.get("data_fine")
        if not din or not dfi:
            raise ValueError("Campi 'data_inizio' e 'data_fine' obbligatori")

        oin = payload.get("ora_inizio", "00:00") or "00:00"
        ofi = payload.get("ora_fine", "00:00") or "00:00"
        include_node = bool(payload.get("include_node", True))
        include_lilith = bool(payload.get("include_lilith", True))

        dt_start = datetime.strptime(f"{din} {oin}", "%Y-%m-%d %H:%M")
        dt_end   = datetime.strptime(f"{dfi} {ofi}", "%Y-%m-%d %H:%M")

        result = transiti_su_due_date(dt_start, dt_end, include_node, include_lilith)
        return {"status": "ok", "result": result}

    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Errore input/processing: {e}")
