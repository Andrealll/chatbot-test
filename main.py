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
            raise HTTPException(status_code=422, detail="Parametri 'citta', 'data' e 'ora' obbligatori.")

        # === Parsing flessibile della data ===
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
                detail="Formato data non riconosciuto. Usa YYYY-MM-DD o DD/MM/YYYY."
            )

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

    except HTTPException as e:
        raise e
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.get("/status")
async def status_check():
    """
    Test diagnostico: verifica disponibilità di servizi e dipendenze.
    """
    from calcoli import df_tutti, calcola_pianeti_da_df, geocodifica_citta_con_fuso
    from metodi import call_ai_model

    results = {}
    try:
        # 1️⃣ Effemeridi
        if df_tutti is None or df_tutti.empty:
            results["effemeridi"] = "❌ non caricate"
        else:
            results["effemeridi"] = f"✅ {len(df_tutti)} righe caricate"

        # 2️⃣ Calcolo rapido pianeti
        try:
            pianeti = calcola_pianeti_da_df(df_tutti, 19, 7, 1986, 8, 50)
            sole = pianeti.get("Sole", {})
            results["calcolo_pianeti"] = f"✅ Sole {sole}" if sole else "⚠️ dati parziali"
        except Exception as e:
            results["calcolo_pianeti"] = f"❌ errore: {e}"

        # 3️⃣ Geocoding (offline o online)
        try:
            info = geocodifica_citta_con_fuso("Napoli", 1986, 7, 19, 8, 50)
            results["geocodifica"] = f"✅ {info['lat']}, {info['lon']} ({info['timezone']})"
        except Exception as e:
            results["geocodifica"] = f"❌ errore: {e}"

        # 4️⃣ Test AI Groq
        try:
            import os
            if os.environ.get("GROQ_API_KEY"):
                response = call_ai_model([
                    {"role": "user", "content": "Scrivi 'ok'."}
                ], max_tokens=10)
                if "ok" in response.lower():
                    results["AI_Groq"] = "✅ risposta corretta"
                else:
                    results["AI_Groq"] = f"⚠️ risposta inattesa: {response}"
            else:
                results["AI_Groq"] = "⚠️ GROQ_API_KEY non impostata"
        except Exception as e:
            results["AI_Groq"] = f"❌ errore: {e}"

        return {
            "status": "ok",
            "message": "Self-test completato",
            "results": results
        }

    except Exception as e:
        return {"status": "error", "message": str(e), "results": results}
 
