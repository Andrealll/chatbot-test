from fastapi import FastAPI, Depends, Response, Cookie
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from typing import Optional, Dict, Any, List
import time
import uuid
from datetime import datetime
from pathlib import Path
from routes_oroscopo import router as oroscopo_router
app.include_router(oroscopo_router)
from astrobot_core.calcoli import (
    df_tutti,
    calcola_asc_mc_case,
    calcola_pianeti_da_df,
    decodifica_segni,
)

from astrobot_core.transiti import calcola_transiti_data_fissa
from astrobot_core.sinastria import sinastria as calcola_sinastria

from astrobot_core.grafici import (
    grafico_tema_natal,
    grafico_sinastria,
    grafico_linee_premium,
)

# Router oroscopo (già esistente)
from routes_oroscopo import router as oroscopo_router


# =========================================================
# MODELLI Pydantic
# =========================================================

class TemaRequest(BaseModel):
    citta: str
    data: str          # es. "1986-07-19"
    ora: str           # es. "08:50"
    nome: Optional[str] = None
    email: Optional[str] = None
    domanda: Optional[str] = None
    scope: Optional[str] = "tema"
    tier: Optional[str] = "free"


class TemaResponse(BaseModel):
    status: str
    elapsed: float
    input: Dict[str, Any]
    tema: Optional[Dict[str, Any]] = None
    interpretazione: Optional[str] = None
    interpretazione_error: Optional[str] = None
    carta_base64: Optional[str] = None
    carta_error: Optional[str] = None
    grafico_polare: Optional[Dict[str, Any]] = None
    png_base64: Optional[str] = None


class Persona(BaseModel):
    citta: str
    data: str          # "YYYY-MM-DD"
    ora: str           # "HH:MM"
    nome: Optional[str] = None


class SinastriaRequest(BaseModel):
    A: Persona
    B: Persona
    scope: Optional[str] = "sinastria"
    tier: Optional[str] = "free"


class SinastriaResponse(BaseModel):
    status: str
    elapsed: float
    input: Dict[str, Any]
    sinastria: Optional[Dict[str, Any]] = None
    grafico_polare: Optional[Dict[str, Any]] = None
    png_base64: Optional[str] = None
    carta_error: Optional[str] = None


class TransitiPremiumRequest(BaseModel):
    """
    Endpoint “render-only”: il core (LLM) ti genera già
    le intensità [0–1] per i 5 domini, tu le passi qui
    e ottieni il grafico PNG base64.
    """
    date_strings: List[str]              # ["2025-11-01", ...]
    intensities: Dict[str, List[float]]  # chiavi attese: energy, emotions, relationships, work, luck
    scope: str = "settimanale"          # "giornaliero" | "settimanale" | "mensile" | "annuale"
    lang: str = "it"                    # "it" | "en" | "es"
    tier: Optional[str] = "free"


class TransitiPremiumResponse(BaseModel):
    status: str
    elapsed: float
    input: Dict[str, Any]
    png_base64: Optional[str] = None
    carta_error: Optional[str] = None


# =========================================================
# HELPER GRAFICI (JSON, non PNG)
# =========================================================

def build_grafico_tema_json(tema: Dict[str, Any]) -> Dict[str, Any]:
    pianeti_decod = tema.get("pianeti_decod", {}) or {}
    asc_mc_case = tema.get("asc_mc_case", {}) or {}

    pianeti = []
    for nome, info in pianeti_decod.items():
        pianeti.append({
            "nome": nome,
            "segno": info.get("segno"),
            "gradi_segno": info.get("gradi_segno"),
            "gradi_eclittici": info.get("gradi_eclittici"),
            "retrogrado": info.get("retrogrado", False),
            "theta": info.get("gradi_eclittici"),
            "r": 1.0,
        })

    case_raw = asc_mc_case.get("case", []) or []
    case = []
    for idx, start_deg in enumerate(case_raw, start=1):
        case.append({
            "casa": idx,
            "inizio": start_deg,
        })

    grafico = {
        "tipo": "tema_polare",
        "pianeti": pianeti,
        "asc": {
            "angolo": asc_mc_case.get("ASC"),
            "segno": asc_mc_case.get("ASC_segno"),
            "gradi_segno": asc_mc_case.get("ASC_gradi_segno"),
        },
        "mc": {
            "angolo": asc_mc_case.get("MC"),
            "segno": asc_mc_case.get("MC_segno"),
            "gradi_segno": asc_mc_case.get("MC_gradi_segno"),
        },
        "case": case,
    }
    return grafico


def build_grafico_sinastria_json(sinastria: Dict[str, Any]) -> Dict[str, Any]:
    serie = []

    tema_A = sinastria.get("A", {}) or {}
    tema_B = sinastria.get("B", {}) or {}

    pianeti_A = []
    for nome, info in (tema_A.get("pianeti_decod", {}) or {}).items():
        pianeti_A.append({
            "nome": nome,
            "segno": info.get("segno"),
            "gradi_segno": info.get("gradi_segno"),
            "gradi_eclittici": info.get("gradi_eclittici"),
            "retrogrado": info.get("retrogrado", False),
            "theta": info.get("gradi_eclittici"),
            "r": 1.0,
        })
    serie.append({"serie": "A", "pianeti": pianeti_A})

    pianeti_B = []
    for nome, info in (tema_B.get("pianeti_decod", {}) or {}).items():
        pianeti_B.append({
            "nome": nome,
            "segno": info.get("segno"),
            "gradi_segno": info.get("gradi_segno"),
            "gradi_eclittici": info.get("gradi_eclittici"),
            "retrogrado": info.get("retrogrado", False),
            "theta": info.get("gradi_eclittici"),
            "r": 0.8,
        })
    serie.append({"serie": "B", "pianeti": pianeti_B})

    return {
        "tipo": "sinastria_polare",
        "serie": serie,
    }


# =========================================================
# APP & CORS
# =========================================================

app = FastAPI(title="Astro API", version="0.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:5173",
        "http://127.0.0.1:3000",
        "*",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(oroscopo_router)


# =========================================================
# LOGICA COOKIE
# =========================================================

COOKIE_USER_ID = "astro_user_id"
COOKIE_SESSION_COUNT = "astro_session_count"
COOKIE_TIER = "astro_tier"


def get_or_set_cookies(
    response: Response,
    astro_user_id: Optional[str] = Cookie(default=None, alias=COOKIE_USER_ID),
    astro_session_count: Optional[str] = Cookie(default=None, alias=COOKIE_SESSION_COUNT),
    astro_tier: Optional[str] = Cookie(default=None, alias=COOKIE_TIER),
) -> Dict[str, Any]:
    new_user_id = astro_user_id
    if not new_user_id:
        new_user_id = str(uuid.uuid4())
        response.set_cookie(
            key=COOKIE_USER_ID,
            value=new_user_id,
            httponly=True,
            samesite="lax",
        )

    try:
        count = int(astro_session_count) if astro_session_count is not None else 0
    except ValueError:
        count = 0
    count += 1
    response.set_cookie(
        key=COOKIE_SESSION_COUNT,
        value=str(count),
        httponly=True,
        samesite="lax",
    )

    return {
        "user_id": new_user_id,
        "session_count": count,
        "tier_cookie": astro_tier,
    }


# =========================================================
# ENDPOINT DI TEST COOKIE
# =========================================================

@app.get("/cookie-test", summary="Ritorna info sui cookie correnti")
def cookie_test(
    response: Response,
    cookie_ctx: Dict[str, Any] = Depends(get_or_set_cookies),
):
    return {
        "status": "ok",
        "cookie_context": cookie_ctx,
    }


@app.post("/cookie-set-tier", summary="Aggiorna il tier nel cookie")
def cookie_set_tier(
    response: Response,
    tier: str,
    cookie_ctx: Dict[str, Any] = Depends(get_or_set_cookies),
):
    response.set_cookie(
        key=COOKIE_TIER,
        value=tier,
        httponly=False,   # leggibile da JS
        samesite="lax",
    )

    return {
        "status": "ok",
        "old_tier": cookie_ctx.get("tier_cookie"),
        "new_tier": tier,
    }


# =========================================================
# ENDPOINT /tema
# =========================================================

@app.post("/tema", response_model=TemaResponse)
def tema_endpoint(
    payload: TemaRequest,
    response: Response,
    cookie_ctx: Dict[str, Any] = Depends(get_or_set_cookies),
):
    """
    Calcola il tema natale completo (pianeti + ASC/MC/case + aspetti)
    usando il core `astrobot_core.transiti.calcola_transiti_data_fissa`
    e genera sia:
    - PNG base64 del grafico polare (grafico_tema_natal)
    - JSON leggero per frontend (build_grafico_tema_json)
    """
    start = time.time()

    # tier → cookie leggibile dal frontend
    if payload.tier:
        response.set_cookie(
            key=COOKIE_TIER,
            value=payload.tier,
            httponly=False,
            samesite="lax",
        )

    tema = None
    carta_base64 = None
    carta_error = None
    grafico_polare = None

    try:
        # parsing data/ora di nascita
        dt = datetime.strptime(f"{payload.data} {payload.ora}", "%Y-%m-%d %H:%M")
        giorno = dt.day
        mese = dt.month
        anno = dt.year
        ora = dt.hour
        minuti = dt.minute

        # usa il core transiti per ottenere pianeti, ASC/MC/case e aspetti del tema
        tema_raw = calcola_transiti_data_fissa(
            giorno=giorno,
            mese=mese,
            anno=anno,
            ora=ora,
            minuti=minuti,
            citta=payload.citta,
            include_node=True,
            include_lilith=True,
        )

        pianeti_decod = tema_raw.get("pianeti_decod", {}) or {}
        asc_mc_case = tema_raw.get("asc_mc_case", {}) or {}
        aspetti = tema_raw.get("aspetti", []) or []

        # payload tema arricchito con info utente
        tema = {
            "data": tema_raw.get("data", dt.strftime("%Y-%m-%d %H:%M")),
            "pianeti_decod": pianeti_decod,
            "asc_mc_case": asc_mc_case,
            "aspetti": aspetti,
            "pianeti": tema_raw.get("pianeti", {}),
            "nome": payload.nome,
            "email": payload.email,
            "domanda": payload.domanda,
        }

        # grafico polare PNG base64 (senza prefisso data:image)
        carta_base64 = grafico_tema_natal(
            pianeti_decod=pianeti_decod,
            asc_mc_case=asc_mc_case,
            aspetti=aspetti,
        )

        # JSON per grafico polare (usato dal frontend React)
        grafico_polare = build_grafico_tema_json(tema)

    except Exception as e:
        tema = None
        carta_base64 = None
        grafico_polare = None
        carta_error = f"Errore generazione tema/carta: {e}"

    # Interpretazione testuale disattivata in questa versione
    interpretazione = None
    interpretazione_error = "Interpretazione disabilitata (Groq non chiamato in questa versione)."

    elapsed = time.time() - start

    # png_base64: con prefisso data:image per il frontend
    png_base64 = carta_base64
    if png_base64 and not png_base64.startswith("data:image/png;base64,"):
        png_base64 = "data:image/png;base64," + png_base64

    return TemaResponse(
        status="ok",
        elapsed=elapsed,
        input=payload.model_dump(),
        tema=tema,
        interpretazione=interpretazione,
        interpretazione_error=interpretazione_error,
        carta_base64=carta_base64,
        carta_error=carta_error,
        grafico_polare=grafico_polare,
        png_base64=png_base64,
    )


# =========================================================
# ENDPOINT /sinastria
# =========================================================

@app.post("/sinastria", response_model=SinastriaResponse)
def sinastria_endpoint(
    payload: SinastriaRequest,
    response: Response,
    cookie_ctx: Dict[str, Any] = Depends(get_or_set_cookies),
):
    """
    Calcola una sinastria completa usando il core
    `astrobot_core.sinastria.sinastria`:

    - Tema A (pianeti + ASC/MC/case)
    - Tema B
    - Aspetti A↔B con orb, conteggi e top aspetti stretti
    - Grafico polare PNG + JSON per il frontend
    """
    start = time.time()

    if payload.tier:
        response.set_cookie(
            key=COOKIE_TIER,
            value=payload.tier,
            httponly=False,
            samesite="lax",
        )

    sinastria_data: Optional[Dict[str, Any]] = None
    carta_base64 = None
    carta_error = None
    grafico_polare = None

    try:
        # parsing date/ora delle due persone
        dt_a = datetime.strptime(f"{payload.A.data} {payload.A.ora}", "%Y-%m-%d %H:%M")
        dt_b = datetime.strptime(f"{payload.B.data} {payload.B.ora}", "%Y-%m-%d %H:%M")

        # delega il calcolo astrologico al core sinastria
        sin_core = calcola_sinastria(
            dt_A=dt_a,
            citta_A=payload.A.citta,
            dt_B=dt_b,
            citta_B=payload.B.citta,
        )

        tema_A = sin_core.get("A", {}) or {}
        tema_B = sin_core.get("B", {}) or {}
        sin_info = sin_core.get("sinastria", {}) or {}

        aspetti_AB = sin_info.get("aspetti_AB", []) or []
        conteggio_per_tipo = sin_info.get("conteggio_per_tipo", {}) or {}
        top_stretti = sin_info.get("top_stretti", []) or []

        # payload sinastria restituito all'API
        sinastria_data = {
            "A": {
                **tema_A,
                "nome": payload.A.nome or "A",
            },
            "B": {
                **tema_B,
                "nome": payload.B.nome or "B",
            },
            "aspetti": aspetti_AB,
            "conteggio_per_tipo": conteggio_per_tipo,
            "top_aspetti_stretti": top_stretti,
        }

        # grafico polare PNG (sinastria completa)
        carta_base64 = grafico_sinastria(
            pianeti_A_decod=tema_A.get("pianeti_decod", {}) or {},
            pianeti_B_decod=tema_B.get("pianeti_decod", {}) or {},
            aspetti_AB=aspetti_AB,
            nome_A=payload.A.nome or "A",
            nome_B=payload.B.nome or "B",
        )

        # JSON per grafico polare sinastria
        grafico_polare = build_grafico_sinastria_json(sinastria_data)

    except Exception as e:
        sinastria_data = None
        carta_base64 = None
        grafico_polare = None
        carta_error = f"Errore generazione sinastria/carta: {e}"

    elapsed = time.time() - start

    png_base64 = carta_base64
    if png_base64 and not png_base64.startswith("data:image/png;base64,"):
        png_base64 = "data:image/png;base64," + png_base64

    return SinastriaResponse(
        status="ok",
        elapsed=elapsed,
        input=payload.model_dump(),
        sinastria=sinastria_data,
        grafico_polare=grafico_polare,
        png_base64=png_base64,
        carta_error=carta_error,
    )


# =========================================================
# ENDPOINT /transiti/premium (line chart 5 dimensioni)
# =========================================================

def _label_map_for_lang(lang: str) -> Dict[str, str]:
    lang = (lang or "it").lower()
    if lang.startswith("en"):
        return {
            "energy": "Energy",
            "emotions": "Emotions",
            "relationships": "Relationships",
            "work": "Work",
            "luck": "Luck",
        }
    if lang.startswith("es"):
        return {
            "energy": "Energía",
            "emotions": "Emociones",
            "relationships": "Relaciones",
            "work": "Trabajo",
            "luck": "Suerte",
        }
    # default IT
    return {
        "energy": "Energia",
        "emotions": "Emozioni",
        "relationships": "Relazioni",
        "work": "Lavoro",
        "luck": "Fortuna",
    }


@app.post("/transiti/premium", response_model=TransitiPremiumResponse)
def transiti_premium_endpoint(
    payload: TransitiPremiumRequest,
    response: Response,
    cookie_ctx: Dict[str, Any] = Depends(get_or_set_cookies),
):
    """
    Endpoint per rendere il grafico a linee premium (5 dimensioni)
    a partire da:
    - date_strings: lista di date "YYYY-MM-DD"
    - intensities: dict {energy, emotions, relationships, work, luck} -> liste [0..1]

    Non calcola i transiti: prende le intensità dal core (LLM/backend)
    e le trasforma in un PNG base64 per il frontend.
    """
    start = time.time()

    if payload.tier:
        response.set_cookie(
            key=COOKIE_TIER,
            value=payload.tier,
            httponly=False,
            samesite="lax",
        )

    carta_error = None
    png_base64 = None

    try:
        # Validazione base lunghezze
        n = len(payload.date_strings)
        if n == 0:
            raise ValueError("date_strings vuoto.")

        for key, serie in payload.intensities.items():
            if len(serie) != n:
                raise ValueError(
                    f"Lunghezza serie '{key}' ({len(serie)}) diversa da date_strings ({n})."
                )

        label_map = _label_map_for_lang(payload.lang)

        img_b64 = grafico_linee_premium(
            date_strings=payload.date_strings,
            intensities_series=payload.intensities,
            scope=payload.scope,
            label_map=label_map,
        )

        png_base64 = img_b64
        if not png_base64.startswith("data:image/png;base64,"):
            png_base64 = "data:image/png;base64," + png_base64

    except Exception as e:
        carta_error = f"Errore generazione grafico transiti premium: {e}"
        png_base64 = None

    elapsed = time.time() - start

    return TransitiPremiumResponse(
        status="ok" if png_base64 else "error",
        elapsed=elapsed,
        input=payload.model_dump(),
        png_base64=png_base64,
        carta_error=carta_error,
    )


# =========================================================
# ROOT → SERVE index.html
# =========================================================

@app.get("/", response_class=HTMLResponse, tags=["Root"])
def root():
    index_path = Path(__file__).parent / "index.html"
    if not index_path.exists():
        return "<h1>AstroBot</h1><p>index.html non trovato.</p>"
    return index_path.read_text(encoding="utf-8")
