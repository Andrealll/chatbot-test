from fastapi import FastAPI, Depends, Response, Cookie, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, Dict, Any
import time
import uuid

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


# =========================================================
# APP & CORS
# =========================================================

app = FastAPI(title="Astro API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:5173", "http://127.0.0.1:3000", "*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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
# ENDPOINT /tema (SENZA GROQ)
# =========================================================

@app.post("/tema", response_model=TemaResponse)
def tema_endpoint(
    payload: TemaRequest,
    response: Response,
    cookie_ctx: Dict[str, Any] = Depends(get_or_set_cookies),
):
    """
    Calcola il tema natale.
    QUI Groq è DISABILITATO. L'interpretazione resta None / messaggio di placeholder.
    """
    start = time.time()

    # Aggiorna cookie tier se nel body arriva qualcosa
    if payload.tier:
        response.set_cookie(
            key=COOKIE_TIER,
            value=payload.tier,
            httponly=False,   # leggibile da frontend
            samesite="lax",
        )

    # Qui metti le tue funzioni reali di calcolo
    # -------------------------------------------------
    # ESEMPIO: sostituisci con i tuoi import reali
    # from servizi.astro import calcola_tema, genera_carta_base64
    # tema = calcola_tema(payload.citta, payload.data, payload.ora, sistema_case="equal")
    # carta_base64 = genera_carta_base64(dati_tema=tema)
    # -------------------------------------------------

    # Per adesso uso un finto tema basato sui dati che mi hai mostrato,
    # giusto per non rompere nulla lato forma JSON:
    tema_finto = {
        "data": f"{payload.data} {payload.ora}",
        "pianeti_decod": {},
        "asc_mc_case": {
            "citta": payload.citta,
            "ASC_segno": "Vergine",
            "ASC_gradi_segno": 1.0,
            "MC_segno": "Toro",
            "MC_gradi_segno": 25.87,
            "sistema_case": "equal",
        },
    }

    # Carta: per ora None, così non esplode se non hai la funzione
    carta_base64 = None
    carta_error = None

    # Interpretazione Groq DISABILITATA VOLONTARIAMENTE
    interpretazione = None
    interpretazione_error = "Interpretazione disabilitata (Groq non chiamato in questa versione)."

    elapsed = time.time() - start

    return TemaResponse(
        status="ok",
        elapsed=elapsed,
        input=payload.model_dump(),
        tema=tema_finto,
        interpretazione=interpretazione,
        interpretazione_error=interpretazione_error,
        carta_base64=carta_base64,
        carta_error=carta_error,
    )


# =========================================================
# ROOT
# =========================================================

@app.get("/")
def root():
    return {
        "status": "ok",
        "message": "Astro API up & running (Groq OFF, cookie logic ON).",
    }
