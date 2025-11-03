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
