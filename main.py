from fastapi import FastAPI, Depends, Response, Cookie
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from typing import Optional, Dict, Any
import time
import uuid
from datetime import datetime
from pathlib import Path

from astrobot_core.calcoli import (
    df_tutti,
    calcola_asc_mc_case,
    calcola_pianeti_da_df,
    decodifica_segni,
    genera_carta_base64,
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
    # T8: aggiunte
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


# =========================================================
# HELPER GRAFICI (JSON)
# =========================================================

def build_grafico_tema_json(tema: Dict[str, Any]) -> Dict[str, Any]:
    """
    Costruisce il JSON per il grafico polare a partire dal dict `tema`
    (pianeti_decod, asc_mc_case, case).
    """
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
            # per il grafico polare
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
    """
    JSON per grafico polare di sinastria: due serie (A e B),
    ciascuna con la propria lista di pianeti.
    """
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
            "r": 0.8,  # r diverso per distinguerli graficamente
        })
    serie.append({"serie": "B", "pianeti": pianeti_B})

    return {
        "tipo": "sinastria_polare",
        "serie": serie,
    }


# =========================================================
# APP & CORS
# =========================================================

app = FastAPI(title="Astro API", version="0.1.0")

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

# Router oroscopo (già esistente)
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
    """
    - Se non c'è user_id → lo crea (UUID) e setta il cookie
    - Incrementa il contatore di sessione
    - Ritorna il contesto cookie per gli endpoint
    """
    # user_id
    new_user_id = astro_user_id
    if not new_user_id:
        new_user_id = str(uuid.uuid4())
        response.set_cookie(
            key=COOKIE_USER_ID,
            value=new_user_id,
            httponly=True,
            samesite="lax",
        )

    # session_count
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

    # tier lo gestiamo negli endpoint (se body.tier diverso, lo aggiorniamo lì)
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
    """
    Endpoint per vedere cosa succede con i cookie:
    - crea user_id se manca
    - incrementa session_count
    - NON tocca il tier
    """
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
    """
    Semplice endpoint per impostare il tier nel cookie (es. 'free', 'pro', ecc.)
    """
    response.set_cookie(
        key=COOKIE_TIER,
        value=tier,
        httponly=False,   # se vuoi leggerlo da JS puoi lasciarlo False
        samesite="lax",
    )

    return {
        "status": "ok",
        "old_tier": cookie_ctx.get("tier_cookie"),
        "new_tier": tier,
    }


# =========================================================
# ENDPOINT /tema (SENZA GROQ, CON GRAFICO POLARE)
# =========================================================

@app.post("/tema", response_model=TemaResponse)
def tema_endpoint(
    payload: TemaRequest,
    response: Response,
    cookie_ctx: Dict[str, Any] = Depends(get_or_set_cookies),
):
    """
    Calcola il tema natale.
    Groq è DISABILITATO: niente interpretazione, solo dati + carta + JSON grafico.
    """
    start = time.time()

    # Aggiorna cookie tier se nel body arriva qualcosa
    if payload.tier:
        response.set_cookie(
            key=COOKIE_TIER,
            value=payload.tier,
            httponly=False,   # leggibile dal frontend
            samesite="lax",
        )

    tema = None
    carta_base64 = None
    carta_error = None
    grafico_polare = None

    try:
        # parsing data/ora
        dt = datetime.strptime(f"{payload.data} {payload.ora}", "%Y-%m-%d %H:%M")
        giorno = dt.day
        mese = dt.month
        anno = dt.year
        ora = dt.hour
        minuti = dt.minute

        # 1) ASC, MC, CASE
        asc_mc_case = calcola_asc_mc_case(
            citta=payload.citta,
            anno=anno,
            mese=mese,
            giorno=giorno,
            ora=ora,
            minuti=minuti,
            sistema_case="equal",
        )

        # 2) Pianeti
        pianeti = calcola_pianeti_da_df(
            df_tutti,
            giorno=giorno,
            mese=mese,
            anno=anno,
            ora=ora,
            minuti=minuti,
        )

        pianeti_decod = decodifica_segni(pianeti)

        # 3) Tema da restituire
        tema = {
            "data": dt.strftime("%Y-%m-%d %H:%M"),
            "pianeti_decod": pianeti_decod,
            "asc_mc_case": asc_mc_case,
        }

        # 4) Carta (grafico polare PNG base64)
        carta_base64 = genera_carta_base64(
            pianeti_decod=pianeti_decod,
            asc_mc_case=asc_mc_case,
            aspetti=None,  # per il solo tema natale possiamo lasciare None
        )

        # 5) JSON per grafico polare
        grafico_polare = build_grafico_tema_json(tema)

    except Exception as e:
        tema = None
        carta_base64 = None
        grafico_polare = None
        carta_error = f"Errore generazione tema/carta: {e}"

    # Interpretazione disattivata in questa versione
    interpretazione = None
    interpretazione_error = "Interpretazione disabilitata (Groq non chiamato in questa versione)."

    elapsed = time.time() - start

    # png_base64: alias con prefisso sicuro
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
# ENDPOINT /sinastria (DUE TEMI + GRAFICO POLARE)
# =========================================================

@app.post("/sinastria", response_model=SinastriaResponse)
def sinastria_endpoint(
    payload: SinastriaRequest,
    response: Response,
    cookie_ctx: Dict[str, Any] = Depends(get_or_set_cookies),
):
    """
    Calcola una sinastria di base:
    - Tema A
    - Tema B
    - placeholder 'aspetti' (da riempire quando usi il core dedicato)
    - PNG base64 (per ora il grafico del tema A)
    - JSON grafico polare con due serie (A e B)
    """
    start = time.time()

    # Aggiorna cookie tier se nel body arriva qualcosa
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
        # Persona A
        dt_a = datetime.strptime(f"{payload.A.data} {payload.A.ora}", "%Y-%m-%d %H:%M")
        g_a, m_a, a_a = dt_a.day, dt_a.month, dt_a.year
        h_a, min_a = dt_a.hour, dt_a.minute

        asc_mc_case_a = calcola_asc_mc_case(
            citta=payload.A.citta,
            anno=a_a,
            mese=m_a,
            giorno=g_a,
            ora=h_a,
            minuti=min_a,
            sistema_case="equal",
        )
        pianeti_a = calcola_pianeti_da_df(
            df_tutti,
            giorno=g_a,
            mese=m_a,
            anno=a_a,
            ora=h_a,
            minuti=min_a,
        )
        pianeti_decod_a = decodifica_segni(pianeti_a)

        # Persona B
        dt_b = datetime.strptime(f"{payload.B.data} {payload.B.ora}", "%Y-%m-%d %H:%M")
        g_b, m_b, a_b = dt_b.day, dt_b.month, dt_b.year
        h_b, min_b = dt_b.hour, dt_b.minute

        asc_mc_case_b = calcola_asc_mc_case(
            citta=payload.B.citta,
            anno=a_b,
            mese=m_b,
            giorno=g_b,
            ora=h_b,
            minuti=min_b,
            sistema_case="equal",
        )
        pianeti_b = calcola_pianeti_da_df(
            df_tutti,
            giorno=g_b,
            mese=m_b,
            anno=a_b,
            ora=h_b,
            minuti=min_b,
        )
        pianeti_decod_b = decodifica_segni(pianeti_b)

        # Sinastria di base (senza aspetti per ora)
        sinastria_data = {
            "A": {
                "data": dt_a.strftime("%Y-%m-%d %H:%M"),
                "pianeti_decod": pianeti_decod_a,
                "asc_mc_case": asc_mc_case_a,
            },
            "B": {
                "data": dt_b.strftime("%Y-%m-%d %H:%M"),
                "pianeti_decod": pianeti_decod_b,
                "asc_mc_case": asc_mc_case_b,
            },
            "aspetti": None,  # TODO: integrare quando userai la funzione sinastria del core
        }

        # PNG base64: per ora riuso la carta del tema A
        carta_base64 = genera_carta_base64(
            pianeti_decod=pianeti_decod_a,
            asc_mc_case=asc_mc_case_a,
            aspetti=None,
        )

        # JSON grafico polare sinastria
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
# ROOT → SERVE index.html
# =========================================================

@app.get("/", response_class=HTMLResponse, tags=["Root"])
def root():
    """
    Serve index.html se presente nella stessa cartella di main.py.
    """
    index_path = Path(__file__).parent / "index.html"
    if not index_path.exists():
        return "<h1>AstroBot</h1><p>index.html non trovato.</p>"
    return index_path.read_text(encoding="utf-8")
