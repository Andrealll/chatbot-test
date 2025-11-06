from fastapi import FastAPI, Request, HTTPException, Body
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Optional, List, Dict
from datetime import datetime
import time

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


# =============================================================================
# APP
# =============================================================================

app = FastAPI(title="AstroBot Service", version="1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def root():
    return {"status": "ok", "message": "AstroBot service online 🪐"}


# =============================================================================
# MODELLI RICHIESTE BASE
# =============================================================================

class TemaRequest(BaseModel):
    citta: str = Field(..., description="Es. 'Napoli, IT'")
    data: str = Field(..., description="Data di nascita YYYY-MM-DD")
    ora: str = Field(..., description="Ora di nascita HH:MM (24h)")
    nome: Optional[str] = None
    email: Optional[str] = None
    domanda: Optional[str] = None
    scope: Optional[str] = "tema"
    tier: Optional[str] = "free"


class SinastriaRequest(BaseModel):
    citta_a: str
    data_a: str  # YYYY-MM-DD
    ora_a: str   # HH:MM
    citta_b: str
    data_b: str  # YYYY-MM-DD
    ora_b: str   # HH:MM
    domanda: Optional[str] = None


# =============================================================================
# ENDPOINT: TEMA NATALE
# =============================================================================
@app.post("/tema", tags=["Tema"], summary="Calcolo tema natale + interpretazione")
async def tema(payload: TemaRequest):
    start = time.time()

    # inizializzo campi / errori per debug
    carta_base64 = None
    carta_error = None
    interpretazione = None
    interpretazione_error = None

    try:
        # 1) Parsing data/ora
        try:
            dt_nascita = datetime.strptime(
                f"{payload.data} {payload.ora}", "%Y-%m-%d %H:%M"
            )
        except ValueError:
            raise HTTPException(
                status_code=422,
                detail="Formato data/ora non valido. Usa data=YYYY-MM-DD e ora=HH:MM.",
            )

        # 2) ASC, MC, Case
        asc_mc_case = calcola_asc_mc_case(
            citta=payload.citta,
            anno=dt_nascita.year,
            mese=dt_nascita.month,
            giorno=dt_nascita.day,
            ora=dt_nascita.hour,
            minuti=dt_nascita.minute,
        )

        # 3) Pianeti (con fallback se la funzione non supporta colonne_extra)
        try:
            # versione “nuova” (se disponibile)
            pianeti = calcola_pianeti_da_df(
                df_tutti,
                giorno=dt_nascita.day,
                mese=dt_nascita.month,
                anno=dt_nascita.year,
                colonne_extra=("Nodo", "Lilith"),
            )
        except TypeError:
            # versione “vecchia” senza colonne_extra
            pianeti = calcola_pianeti_da_df(
                df_tutti,
                giorno=dt_nascita.day,
                mese=dt_nascita.month,
                anno=dt_nascita.year,
            )

        pianeti_decod = decodifica_segni(pianeti)

        # 4) Grafico polare (isolato in try/except)
        try:
            carta_base64 = genera_carta_base64(
                anno=dt_nascita.year,
                mese=dt_nascita.month,
                giorno=dt_nascita.day,
                ora=dt_nascita.hour,
                minuti=dt_nascita.minute,
                lat=asc_mc_case["lat"],
                lon=asc_mc_case["lon"],
                fuso_orario=asc_mc_case["fuso_orario"],
                sistema_case="placidus",
                include_node=True,
                include_lilith=True,
                mostra_asc=True,
                mostra_mc=True,
                titolo=None,
            )
        except Exception as e:
            carta_error = f"Errore genera_carta_base64: {e}"

        # 5) Interpretazione Groq (isolata in try/except)
        try:
            interpretazione = interpreta_groq(
                nome=payload.nome,
                citta=payload.citta,
                data_nascita=payload.data,
                ora_nascita=payload.ora,
                pianeti=pianeti_decod,
                asc_mc_case=asc_mc_case,
                domanda=payload.domanda,
                scope=payload.scope or "tema",
            )
        except Exception as e:
            interpretazione_error = f"Errore interpreta_groq: {e}"

        elapsed = time.time() - start

        return {
            "status": "ok",
            "elapsed": elapsed,
            "input": payload.dict(),
            "tema": {
                "data": dt_nascita.strftime("%Y-%m-%d %H:%M"),
                "pianeti": pianeti,
                "pianeti_decod": pianeti_decod,
                "asc_mc_case": asc_mc_case,
            },
            "interpretazione": interpretazione,
            "interpretazione_error": interpretazione_error,
            "carta_base64": carta_base64,
            "carta_error": carta_error,
        }

    except HTTPException:
        # errori di validazione li rilanciamo
        raise
    except Exception as e:
        # fallback generico
        raise HTTPException(status_code=500, detail=f"Errore interno /tema: {e}")

# =============================================================================
# ENDPOINT: SINASTRIA
# =============================================================================

@app.post("/sinastria", tags=["Sinastria"], summary="Sinastria tra due temi natali")
async def api_sinastria(req: SinastriaRequest):
    try:
        out = calcola_sinastria(
            citta_a=req.citta_a,
            data_a=req.data_a,
            ora_a=req.ora_a,
            citta_b=req.citta_b,
            data_b=req.data_b,
            ora_b=req.ora_b,
            domanda=req.domanda,
        )
        return {"status": "ok", "result": out}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Errore sinastria: {e}")


# =============================================================================
# TRANSITI: DATA FISSA (/transiti)
# =============================================================================

class TransitiReq(BaseModel):
    giorno: int
    mese: int
    anno: int
    lat: Optional[float] = None
    lon: Optional[float] = None
    fuso_orario: float = 0.0
    aspetti: Optional[List[str]] = None
    orb: Optional[Dict[str, float]] = None
    include_node: bool = True
    include_lilith: bool = True


@app.post("/transiti", tags=["Transiti"], summary="Calcolo transiti su data fissa (POST)")
def transiti_post(req: TransitiReq):
    if calcola_transiti_data_fissa is None:
        raise HTTPException(
            status_code=501,
            detail="Funzione calcola_transiti_data_fissa non disponibile."
        )

    return calcola_transiti_data_fissa(
        giorno=req.giorno,
        mese=req.mese,
        anno=req.anno,
        lat=req.lat,
        lon=req.lon,
        fuso_orario=req.fuso_orario,
        aspetti=req.aspetti,
        orb=req.orb,
        include_node=req.include_node,
        include_lilith=req.include_lilith,
    )


@app.get("/transiti", tags=["Transiti"], summary="Calcolo transiti su data fissa (GET)")
def transiti_get(
    giorno: int,
    mese: int,
    anno: int,
    lat: Optional[float] = None,
    lon: Optional[float] = None,
    fuso_orario: float = 0.0,
    include_node: bool = True,
    include_lilith: bool = True,
):
    if calcola_transiti_data_fissa is None:
        raise HTTPException(
            status_code=501,
            detail="Funzione calcola_transiti_data_fissa non disponibile."
        )

    return calcola_transiti_data_fissa(
        giorno=giorno,
        mese=mese,
        anno=anno,
        lat=lat,
        lon=lon,
        fuso_orario=fuso_orario,
        include_node=include_node,
        include_lilith=include_lilith,
    )


# =============================================================================
# TRANSITI: DUE DATE (se presente)
# =============================================================================

class TransitiDueDateRequest(BaseModel):
    giorno1: int
    mese1: int
    anno1: int
    giorno2: int
    mese2: int
    anno2: int
    lat: Optional[float] = None
    lon: Optional[float] = None
    fuso_orario: float = 0.0
    include_node: bool = True
    include_lilith: bool = True


@app.post("/transiti-due-date", tags=["Transiti"], summary="Transiti tra due date (se supportato)")
async def transiti_due_date(body: TransitiDueDateRequest):
    if transiti_su_due_date is None:
        raise HTTPException(
            status_code=501,
            detail="Funzione transiti_su_due_date non disponibile in questa build."
        )
    try:
        out = transiti_su_due_date(
            giorno1=body.giorno1,
            mese1=body.mese1,
            anno1=body.anno1,
            giorno2=body.giorno2,
            mese2=body.mese2,
            anno2=body.anno2,
            lat=body.lat,
            lon=body.lon,
            fuso_orario=body.fuso_orario,
            include_node=body.include_node,
            include_lilith=body.include_lilith,
        )
        return {"status": "ok", "result": out}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Errore transiti-due-date: {e}")


# =============================================================================
# TRANSITI: VS NATALE (nuovi)
# =============================================================================

class TransitiVsNatalReq(BaseModel):
    citta: str = Field(..., description="Es. 'Napoli, IT'")
    data: str = Field(..., description="Data di nascita YYYY-MM-DD")
    ora: str = Field(..., description="Ora di nascita HH:MM (24h)")
    quando: Optional[str] = Field(
        None,
        description="Data/ora transito (YYYY-MM-DD o YYYY-MM-DD HH:MM). Se omesso, oggi ore 12:00.",
    )
    include_node: bool = True
    include_lilith: bool = True
    filtra_transito: Optional[List[str]] = None
    filtra_natal: Optional[List[str]] = None


def _parse_quando(s: Optional[str]) -> datetime:
    """Parsa 'quando' con alcuni formati comodi; default=oggi 12:00."""
    if not s:
        return datetime.now().replace(hour=12, minute=0, second=0, microsecond=0)

    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d", "%d/%m/%Y %H:%M", "%d/%m/%Y"):
        try:
            dt = datetime.strptime(s, fmt)
            if fmt in ("%Y-%m-%d", "%d/%m/%Y"):
                dt = dt.replace(hour=12, minute=0)
            return dt
        except ValueError:
            continue

    raise HTTPException(
        status_code=422,
        detail="Formato 'quando' non valido. Usa 'YYYY-MM-DD' o 'YYYY-MM-DD HH:MM'.",
    )


@app.post("/transiti-vs-natal", tags=["Transiti"], summary="Aspetti tra pianeti di transito e tema natale")
async def api_transiti_vs_natal(req: TransitiVsNatalReq):
    if transiti_vs_natal_in_data is None:
        raise HTTPException(
            status_code=501,
            detail="Funzione transiti_vs_natal_in_data non disponibile in questa build di astrobot_core."
        )

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


# =============================================================================
# TRANSITI: OGGI
# =============================================================================

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
    # se manca la funzione specifica, fallback a transiti_vs_natal_in_data con quando=oggi
    if transiti_oggi is None:
        if transiti_vs_natal_in_data is None:
            raise HTTPException(
                status_code=501,
                detail="Funzione transiti_oggi/transiti_vs_natal_in_data non disponibile."
            )

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


# =============================================================================
# TRANSITI: PERIODO (se presente)
# =============================================================================

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
        raise HTTPException(
            status_code=501,
            detail="Funzione transiti_su_periodo non disponibile nella versione attuale di astrobot_core."
        )

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

    # la funzione può restituire un dict con status
    if isinstance(out, dict) and out.get("status") != "ok":
        return {"status": "error", "detail": out}

    return out
