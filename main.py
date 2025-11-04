from fastapi import FastAPI, Request, HTTPException, Body
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Optional, List, Dict
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

# transiti: import best-effort (alcune funzioni potrebbero non esistere in alcune build)
calcola_transiti_data_fissa = None
transiti_su_due_date = None
transiti_vs_natal_in_data = None
transiti_oggi = None
transiti_su_periodo = None
try:
    from astrobot_core.transiti import calcola_transiti_data_fissa as _ctdf
    calcola_transiti_data_fissa = _ctdf
except Exception:
    pass

try:
    from astrobot_core.transiti import transiti_su_due_date as _tsdd
    transiti_su_due_date = _tsdd
except Exception:
    pass

try:
    from astrobot_core.transiti import transiti_vs_natal_in_data as _tvnid
    transiti_vs_natal_in_data = _tvnid
except Exception:
    pass

try:
    from astrobot_core.transiti import transiti_oggi as _toggi
    transiti_oggi = _toggi
except Exception:
    pass

try:
    from astrobot_core.transiti import transiti_su_periodo as _tperiodo
    transiti_su_periodo = _tperiodo
except Exception:
    pass

# ====================== AGGIUNTE (minime) ======================
# Supabase server-side (opzionale: usato dai router demo se necessario)
try:
    from supabase import create_client, Client
    SUPABASE_URL = os.environ.get("SUPABASE_URL")
    SUPABASE_SERVICE_ROLE = os.environ.get("SUPABASE_SERVICE_ROLE")
    supabase: "Client | None" = (
        create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE)
        if SUPABASE_URL and SUPABASE_SERVICE_ROLE else None
    )
except Exception:
    supabase = None  # proseguiamo anche senza Supabase

# Rate limit (Redis) startup
try:
    from ratelimit import rl_startup
except Exception:
    rl_startup = None  # se non presente, nessun errore

# Router DEMO (senza login) con quota giornaliera
# (richiede routes_demo.py con build_demo_router)
try:
    from routes_demo import build_demo_router
except Exception:
    build_demo_router = None
# ===============================================================

app = FastAPI(title="AstroBot v13", version="13.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # restringi se necessario
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ====================== AGGIUNTE (minime) ======================
# Monta il router /demo solo se disponibile
if build_demo_router is not None:
    app.include_router(build_demo_router(supabase), tags=["Demo"])

# Inizializza Redis rate-limit se disponibile
@app.on_event("startup")
async def _startup():
    if rl_startup is not None:
        await rl_startup()
# ===============================================================

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
    import astrobot_core.transiti as core_transiti
    import astrobot_core.sinastria as core_sinastria

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

        # path dei moduli effettivamente caricati
        results["module_paths"] = {
            "astrobot_core.transiti": getattr(core_transiti, "__file__", None),
            "astrobot_core.sinastria": getattr(core_sinastria, "__file__", None),
        }

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
    if calcola_transiti_data_fissa is None:
        raise HTTPException(status_code=501, detail="Funzione calcola_transiti_data_fissa non disponibile.")
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
    if calcola_transiti_data_fissa is None:
        raise HTTPException(status_code=501, detail="Funzione calcola_transiti_data_fissa non disponibile.")
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
        if transiti_su_due_date is None:
            raise HTTPException(status_code=501, detail="Funzione transiti_su_due_date non disponibile nella versione attuale di astrobot_core.")

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

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Errore input/processing: {e}")

# --------------------------- TRANSITI: VS NATALE (nuovi) ---------------------------

class TransitiVsNatalReq(BaseModel):
    citta: str = Field(..., description="Es. 'Napoli, IT'")
    data: str = Field(..., description="Data di nascita YYYY-MM-DD")
    ora: str = Field(..., description="Ora di nascita HH:MM (24h)")
    quando: Optional[str] = Field(None, description="Data/ora transito (YYYY-MM-DD o YYYY-MM-DD HH:MM). Se omesso, usa /transiti-oggi.")
    include_node: bool = True
    include_lilith: bool = True
    filtra_transito: Optional[List[str]] = None
    filtra_natal: Optional[List[str]] = None

def _parse_quando(s: Optional[str]) -> datetime:
    """Parsa 'quando' con alcuni formati comodi; default=oggi 12:00."""
    if not s:
        return datetime.now().replace(hour=12, minute=0, second=0, microsecond=0)
    # prova diversi formati
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d", "%d/%m/%Y %H:%M", "%d/%m/%Y"):
        try:
            dt = datetime.strptime(s, fmt)
            if fmt in ("%Y-%m-%d", "%d/%m/%Y"):
                dt = dt.replace(hour=12, minute=0)
            return dt
        except ValueError:
            continue
    raise HTTPException(status_code=422, detail="Formato 'quando' non valido. Usa 'YYYY-MM-DD' o 'YYYY-MM-DD HH:MM'.")

@app.post("/transiti-vs-natal", tags=["Transiti"], summary="Aspetti tra pianeti di transito e tema natale")
async def api_transiti_vs_natal(req: TransitiVsNatalReq):
    if transiti_vs_natal_in_data is None:
        raise HTTPException(status_code=501, detail="Funzione transiti_vs_natal_in_data non disponibile in questa build di astrobot_core.")
    quando_dt = _parse_quando(req.quando)
    out = transiti_vs_natal_in_data(
        citta=req.citta,
        data_nascita=req.data,
        ora_nascita=req.ora,
        quando=quando_dt,
        include_node=req.include_node,
        include_lilith=req.include_lilith,
        filtra_transito=req.filtra_transito,
        filtra_natal=req.filtra_natal,
    )
    return {"status": "ok", "result": out}

class TransitiOggiReq(BaseModel):
    citta: str
    data: str  # YYYY-MM-DD
    ora: str   # HH:MM
    include_node: bool = True
    include_lilith: bool = True
    filtra_transito: Optional[List[str]] = None
    filtra_natal: Optional[List[str]] = None

@app.post("/transiti-oggi", tags=["Transiti"], summary="Aspetti transiti di oggi (ore 12:00) vs tema natale")
async def api_transiti_oggi(req: TransitiOggiReq):
    if transiti_oggi is None:
        # fallback gentile: prova /transiti-vs-natal con quando=oggi
        if transiti_vs_natal_in_data is None:
            raise HTTPException(status_code=501, detail="Funzione transiti_oggi/transiti_vs_natal_in_data non disponibile.")
        quando_dt = _parse_quando(None)
        out = transiti_vs_natal_in_data(
            citta=req.citta,
            data_nascita=req.data,
            ora_nascita=req.ora,
            quando=quando_dt,
            include_node=req.include_node,
            include_lilith=req.include_lilith,
            filtra_transito=req.filtra_transito,
            filtra_natal=req.filtra_natal,
        )
        return {"status": "ok", "result": out}

    out = transiti_oggi(
        citta=req.citta,
        data_nascita=req.data,
        ora_nascita=req.ora,
        include_node=req.include_node,
        include_lilith=req.include_lilith,
        filtra_transito=req.filtra_transito,
        filtra_natal=req.filtra_natal,
    )
    return {"status": "ok", "result": out}

# --------------------------- TRANSITI: PERIODO (nuovo, se presente) ---------------------------

class TransitiPeriodoRequest(BaseModel):
    citta: str = Field(..., description="Es. 'Milano, IT'")
    data: str = Field(..., description="Data di nascita YYYY-MM-DD")
    ora: str = Field(..., description="Ora di nascita HH:MM (24h)")
    start: str = Field(..., description="Inizio periodo YYYY-MM-DD")
    end: str = Field(..., description="Fine periodo YYYY-MM-DD")
    step_days: int = 1
    aspetti: Optional[List[str]] = None
    orb: Optional[Dict[str, float]] = None
    include_node: bool = True
    include_lilith: bool = True
    filtra_transito: Optional[List[str]] = None
    filtra_natal: Optional[List[str]] = None

@app.post("/transiti-periodo", tags=["Transiti"], summary="Transiti vs tema natale su un periodo (giornaliero)")
async def api_transiti_periodo(body: TransitiPeriodoRequest):
    if transiti_su_periodo is None:
        raise HTTPException(status_code=501, detail="Funzione transiti_su_periodo non disponibile nella versione attuale di astrobot_core.")
    out = transiti_su_periodo(
        citta=body.citta,
        data_nascita=body.data,
        ora_nascita=body.ora,
        start=body.start,
        end=body.end,
        step_days=body.step_days,
        aspetti=body.aspetti,
        orb=body.orb,
        include_node=body.include_node,
        include_lilith=body.include_lilith,
        filtra_transito=body.filtra_transito,
        filtra_natal=body.filtra_natal,
    )
    if out.get("status") != "ok":
        return {"status": "error", "detail": out}
    return out
