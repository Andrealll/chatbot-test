from fastapi import FastAPI, Depends, Response, Cookie
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from typing import Optional, Dict, Any, List, Literal  # ← AGGIUNTO Literal
import time, uuid
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
load_dotenv()
import logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
# === DEBUG CREDITS / SUPABASE ===
try:
    from credits_logic import SUPABASE_URL, USE_SUPABASE
except Exception:
    # Se credits_logic non è importabile per qualunque motivo,
    # evitiamo che l'app vada in crash e mostriamo valori di fallback.
    SUPABASE_URL = None
    USE_SUPABASE = False

print("[DEBUG] main import start")

# ---------------------------------------------------------
# SECURITY (vecchio sistema, usato solo per /auth/token e /auth/me locale)
# ---------------------------------------------------------
try:
    from security import sign_jwt, get_user_context_required
    _security_ok = True
    print("[DEBUG] security import OK")
except Exception as e:
    _security_ok = False
    print(f"[WARN] security import FAILED: {e}")

    def sign_jwt(sub: str, role: str, name: Optional[str] = None, email: Optional[str] = None) -> str:
        return f"dummy.{role}.{sub}"

    def get_current_user_required():
        raise RuntimeError("Security non disponibile in locale: controlla security.py e .env")


# ---------------------------------------------------------
# AUTH (nuovo sistema JWT: token emessi da astrobot_auth)
# ---------------------------------------------------------
try:
    # auth.py deve stare nello stesso repo di chatbot-test
    from auth import get_current_user, UserContext
    _auth_ok = True
    print("[DEBUG] auth import OK")
except Exception as e:
    _auth_ok = False
    print(f"[WARN] auth import FAILED: {e}")

    class UserContext(BaseModel):
        sub: str = "anonymous"
        role: str = "free"

    def get_current_user():
        raise RuntimeError("Auth non disponibile: controlla auth.py")


# ---------------------------------------------------------
# APP & CORS
# ---------------------------------------------------------
app = FastAPI(title="Astro API", version="0.2.0")
print("[DEBUG] app created")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:5173",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:5173",
        "*",  # comodo per test
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
print("[DEBUG] CORS middleware added")


# ---- HEALTH & HELLO (devono comparire SEMPRE) ----------------
@app.get("/healthz", tags=["Health"])
def healthz():
    return {"status": "ok"}


@app.get("/hello", tags=["Health"])
def hello():
    return {"hello": "world"}


# Startup: stampa le route registrate
@app.on_event("startup")
async def _debug_routes():
    print("\n=== ROUTES REGISTRATE ===")
    for r in app.routes:
        print(f"{r.path}  {getattr(r, 'methods', None)}")
    print("=== FINE ROUTES ===\n")


# ---------------------------------------------------------
# MODELLI (pydantic)
# ---------------------------------------------------------
class TemaRequest(BaseModel):
    citta: str
    data: str          # "YYYY-MM-DD"
    ora: str           # "HH:MM"
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
    role: Optional[str] = None   # 👈 ruolo effettivo (free/premium) letto dal token


class Persona(BaseModel):
    citta: str
    data: str
    ora: str
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
    date_strings: List[str]
    intensities: Dict[str, List[float]]
    scope: str = "settimanale"     # "giornaliero" | "settimanale" | "mensile" | "annuale"
    lang: str = "it"               # "it" | "en" | "es"
    tier: Optional[str] = "free"


class TransitiPremiumResponse(BaseModel):
    status: str
    elapsed: float
    input: Dict[str, Any]
    png_base64: Optional[str] = None
    carta_error: Optional[str] = None


class TokenRequest(BaseModel):
    role: str = "free"             # "free" | "premium"
    name: Optional[str] = None
    email: Optional[str] = None


# 👇 AGGIUNTO: modello semplificato per il sito DYANA
class OroscopoSiteRequest(BaseModel):
    """
    Richiesta semplificata che arriva dal sito DYANA.
    """
    nome: Optional[str] = None
    citta: str
    data_nascita: str        # "YYYY-MM-DD"
    ora_nascita: str         # "HH:MM"
    periodo: Literal["giornaliero", "settimanale", "mensile", "annuale"]
    tier: Literal["free", "premium", "auto"] = "auto"


print("[DEBUG] models defined")


# ---------------------------------------------------------
# UTILS: Cookie + label map
# ---------------------------------------------------------
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
        response.set_cookie(key=COOKIE_USER_ID, value=new_user_id, httponly=True, samesite="lax")
    try:
        count = int(astro_session_count) if astro_session_count is not None else 0
    except ValueError:
        count = 0
    count += 1
    response.set_cookie(key=COOKIE_SESSION_COUNT, value=str(count), httponly=True, samesite="lax")
    return {"user_id": new_user_id, "session_count": count, "tier_cookie": astro_tier}


def _label_map_for_lang(lang: str) -> Dict[str, str]:
    lang = (lang or "it").lower()
    if lang.startswith("en"):
        return {"energy": "Energy", "emotions": "Emotions", "relationships": "Relationships", "work": "Work", "luck": "Luck"}
    if lang.startswith("es"):
        return {"energy": "Energía", "emotions": "Emociones", "relationships": "Relaciones", "work": "Trabajo", "luck": "Suerte"}
    return {"energy": "Energia", "emotions": "Emozioni", "relationships": "Relazioni", "work": "Lavoro", "luck": "Fortuna"}


def _blank_png_no_prefix() -> str:
    # PNG 1x1 trasparente, senza prefisso data:image
    return "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR4nGNgYAAAAAMAASsJTYQAAAAASUVORK5CYII="


# 👇 AGGIUNTO: risoluzione tier per il sito
def _resolve_tier_for_site(req_tier: str) -> str:
    """
    Per ora:
    - se il frontend specifica 'free' o 'premium', usiamo quello
    - se manda 'auto' (o niente), trattiamo come 'free'
    Più avanti qui leggeremo il JWT per capire il tier reale.
    """
    value = (req_tier or "").lower()
    if value in ("free", "premium"):
        return value
    return "free"


print("[DEBUG] utils ready")


# ---------------------------------------------------------
# AUTH (JWT LOCALE /auth/token e /auth/me basati su security.py)
# ---------------------------------------------------------
@app.post("/auth/token", tags=["Auth"])
def issue_token(body: TokenRequest):
    sub = str(uuid.uuid4())
    token = sign_jwt(sub=sub, role=body.role, name=body.name, email=body.email)
    return {"access_token": token, "token_type": "Bearer", "role": body.role, "sub": sub}


if _security_ok:
    @app.get("/auth/me", tags=["Auth"])
    def whoami(ctx=Depends(get_user_context_required)):
        return {"user": ctx["sub"], "role": ctx["role"], "claims": ctx["claims"]}
else:
    @app.get("/auth/me", tags=["Auth"])
    def whoami_nosec():
        return {"error": "security non disponibile in locale", "hint": "controlla security.py e .env"}


print("[DEBUG] auth routes defined")


# ---------------------------------------------------------
# /tema — PROTETTO CON JWT da astrobot_auth + FALLBACK
# ---------------------------------------------------------
@app.post("/tema", response_model=TemaResponse, tags=["Tema"])
def tema_endpoint(
    payload: TemaRequest,
    response: Response,
    cookie_ctx: Dict[str, Any] = Depends(get_or_set_cookies),
    user: UserContext = Depends(get_current_user),  # 👈 legge sub + role dal token Bearer
):
    start = time.time()

    # Tier effettivo preso DAL TOKEN (role = "free" | "premium")
    effective_role = getattr(user, "role", None) or (payload.tier or "free")

    # Salviamo comunque il tier in cookie per debug/tracking frontend
    response.set_cookie(key=COOKIE_TIER, value=effective_role, httponly=False, samesite="lax")

    tema = None
    carta_base64 = None
    carta_error = None
    grafico_polare = None

    try:
        # PROVA A USARE I CALCOLI REALI (se astrobot_core è installato)
        from astrobot_core.transiti import calcola_transiti_data_fissa
        try:
            from astrobot_core.grafici import grafico_tema_natal
            _use_blank = False
        except Exception:
            _use_blank = True

        dt = datetime.strptime(f"{payload.data} {payload.ora}", "%Y-%m-%d %H:%M")
        tema_raw = calcola_transiti_data_fissa(
            giorno=dt.day,
            mese=dt.month,
            anno=dt.year,
            ora=dt.hour,
            minuti=dt.minute,
            citta=payload.citta,
            include_node=True,
            include_lilith=True,
        )

        pianeti_decod = tema_raw.get("pianeti_decod", {}) or {}
        asc_mc_case = tema_raw.get("asc_mc_case", {}) or {}
        aspetti = tema_raw.get("aspetti", []) or []

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

        if _use_blank:
            carta_base64 = _blank_png_no_prefix()
        else:
            carta_base64 = grafico_tema_natal(
                pianeti_decod=pianeti_decod,
                asc_mc_case=asc_mc_case,
                aspetti=aspetti,
            )

        # JSON leggero per frontend (se abbiamo dati veri)
        pianeti = [
            {
                "nome": n,
                "segno": i.get("segno"),
                "gradi_segno": i.get("gradi_segno"),
                "gradi_eclittici": i.get("gradi_eclittici"),
                "retrogrado": i.get("retrogrado", False),
                "theta": i.get("gradi_eclittici"),
                "r": 1.0,
            }
            for n, i in pianeti_decod.items()
        ]

        case = [{"casa": k + 1, "inizio": d} for k, d in enumerate(asc_mc_case.get("case", []) or [])]

        grafico_polare = {
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

    except ModuleNotFoundError as e:
        # FALLBACK: astrobot_core non è installato in questo ambiente
        carta_error = f"Modulo astrobot_core non disponibile: {e}"
        tema = {
            "data": f"{payload.data} {payload.ora}",
            "pianeti_decod": {},
            "asc_mc_case": {},
            "aspetti": [],
            "pianeti": {},
            "nome": payload.nome,
            "email": payload.email,
            "domanda": payload.domanda,
            "note": "Fallback: astrobot_core non installato, tema simulato.",
        }
        grafico_polare = None
        if effective_role == "premium":
            carta_base64 = _blank_png_no_prefix()

    except Exception as e:
        carta_error = f"Errore generazione tema/carta: {e}"

    interpretazione = None
    interpretazione_error = "Interpretazione disabilitata."

    elapsed = time.time() - start

    png_base64 = carta_base64
    if png_base64 and not png_base64.startswith("data:image/png;base64,"):
        png_base64 = "data:image/png;base64," + png_base64

    # 👇 GATING FREE/PREMIUM:
    # - FREE    -> niente carta_base64 / png_base64
    # - PREMIUM -> carta_base64 + png_base64 se disponibili
    if effective_role != "premium":
        carta_base64 = None
        png_base64 = None

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
        role=effective_role,
    )


print("[DEBUG] /tema defined")


# ---------------------------------------------------------
# /sinastria — import pigri + fallback grafico (NON ancora protetta da JWT)
# ---------------------------------------------------------
@app.post("/sinastria", response_model=SinastriaResponse, tags=["Sinastria"])
def sinastria_endpoint(
    payload: SinastriaRequest,
    response: Response,
    cookie_ctx: Dict[str, Any] = Depends(get_or_set_cookies),
):
    start = time.time()

    if payload.tier:
        response.set_cookie(key=COOKIE_TIER, value=payload.tier, httponly=False, samesite="lax")

    sinastria_data = None
    carta_base64 = None
    carta_error = None
    grafico_polare = None

    try:
        from astrobot_core.sinastria import sinastria as calcola_sinastria
        try:
            from astrobot_core.grafici import grafico_sinastria
            _use_blank = False
        except Exception:
            _use_blank = True

        dt_a = datetime.strptime(f"{payload.A.data} {payload.A.ora}", "%Y-%m-%d %H:%M")
        dt_b = datetime.strptime(f"{payload.B.data} {payload.B.ora}", "%Y-%m-%d %H:%M")

        sin_core = calcola_sinastria(
            dt_A=dt_a, citta_A=payload.A.citta, dt_B=dt_b, citta_B=payload.B.citta
        )
        tema_A, tema_B = sin_core.get("A", {}) or {}, sin_core.get("B", {}) or {}
        sin_info = sin_core.get("sinastria", {}) or {}
        aspetti_AB = sin_info.get("aspetti_AB", []) or []
        conteggio_per_tipo = sin_info.get("conteggio_per_tipo", {}) or {}
        top_stretti = sin_info.get("top_stretti", []) or []

        sinastria_data = {
            "A": {**tema_A, "nome": payload.A.nome or "A"},
            "B": {**tema_B, "nome": payload.B.nome or "B"},
            "aspetti": aspetti_AB,
            "conteggio_per_tipo": conteggio_per_tipo,
            "top_aspetti_stretti": top_stretti,
        }

        if _use_blank:
            carta_base64 = _blank_png_no_prefix()
        else:
            carta_base64 = grafico_sinastria(
                pianeti_A_decod=tema_A.get("pianeti_decod", {}) or {},
                pianeti_B_decod=tema_B.get("pianeti_decod", {}) or {},
                aspetti_AB=aspetti_AB,
                nome_A=payload.A.nome or "A",
                nome_B=payload.B.nome or "B",
            )

        # JSON leggero sinastria
        serie = []
        pianeti_A = [
            {
                "nome": n,
                "segno": i.get("segno"),
                "gradi_segno": i.get("gradi_segno"),
                "gradi_eclittici": i.get("gradi_eclittici"),
                "retrogrado": i.get("retrogrado", False),
                "theta": i.get("gradi_eclittici"),
                "r": 1.0,
            }
            for n, i in (tema_A.get("pianeti_decod", {}) or {}).items()
        ]
        pianeti_B = [
            {
                "nome": n,
                "segno": i.get("segno"),
                "gradi_segno": i.get("gradi_segno"),
                "gradi_eclittici": i.get("gradi_eclittici"),
                "retrogrado": i.get("retrogrado", False),
                "theta": i.get("gradi_eclittici"),
                "r": 0.8,
            }
            for n, i in (tema_B.get("pianeti_decod", {}) or {}).items()
        ]
        serie.append({"serie": "A", "pianeti": pianeti_A})
        serie.append({"serie": "B", "pianeti": pianeti_B})
        grafico_polare = {"tipo": "sinastria_polare", "serie": serie}

    except Exception as e:
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


print("[DEBUG] /sinastria defined")


# ---------------------------------------------------------
# /transiti/premium — import pigri + fallback
# ---------------------------------------------------------
@app.post("/transiti/premium", response_model=TransitiPremiumResponse, tags=["Transiti"])
def transiti_premium_endpoint(
    payload: TransitiPremiumRequest,
    response: Response,
    cookie_ctx: Dict[str, Any] = Depends(get_or_set_cookies),
):
    start = time.time()

    if payload.tier:
        response.set_cookie(key=COOKIE_TIER, value=payload.tier, httponly=False, samesite="lax")

    carta_error = None
    png_base64 = None
    try:
        try:
            from astrobot_core.grafici import grafico_linee_premium
            _use_blank = False
        except Exception:
            _use_blank = True

        n = len(payload.date_strings)
        if n == 0:
            raise ValueError("date_strings vuoto.")
        for key, serie in payload.intensities.items():
            if len(serie) != n:
                raise ValueError(
                    f"Lunghezza serie '{key}' ({len(serie)}) diversa da date_strings ({n})."
                )

        label_map = _label_map_for_lang(payload.lang)
        if _use_blank:
            png_base64 = _blank_png_no_prefix()
        else:
            img_b64 = grafico_linee_premium(
                date_strings=payload.date_strings,
                intensities_series=payload.intensities,
                scope=payload.scope,
                label_map=label_map,
            )
            png_base64 = img_b64

        if png_base64 and not png_base64.startswith("data:image/png;base64,"):
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


print("[DEBUG] /transiti/premium defined")
print("[DEBUG] /transiti/premium defined")

# ---------------------------------------------------------
# ROUTER TEMA_AI (separato)
# ---------------------------------------------------------
try:
    from routes.routes_tema_ai import router as tema_ai_router

    app.include_router(tema_ai_router)
    print("[DEBUG] routes_tema_ai included")
except Exception as e:
    print(f"[WARN] routes_tema_ai non caricato: {e}")

# ---------------------------------------------------------
# ROUTER DYANA (opzionale)
# ---------------------------------------------------------
try:
    from routes_diyana  import router as diyana_router

    app.include_router(diyana_router)
    print("[DEBUG] routes_diyana_ included")
except Exception as e:
    print(f"[WARN] routes_diyana non caricato: {e}")


# ---------------------------------------------------------
# ROUTER OROSCOPO AI (opzionale)
# ---------------------------------------------------------
try:
    # 👇 usa il file routes/routes_oroscopo_ai.py
    from routes.routes_oroscopo_ai import router as oroscopo_ai_router

    app.include_router(oroscopo_ai_router)
    print("[DEBUG] routes_oroscopo_ai included")
except Exception as e:
    print(f"[WARN] routes_oroscopo_ai non caricato: {e}")


# ---------------------------------------------------------
# ROUTER DEBUG (save-image, etc.)
# ---------------------------------------------------------
try:
    from routes_debug import router as debug_router

    app.include_router(debug_router)
    print("[DEBUG] routes_debug included")
except Exception as e:
    print(f"[WARN] routes_debug non caricato: {e}")



# ---------------------------------------------------------
# ROOT
# ---------------------------------------------------------
@app.get("/", response_class=HTMLResponse, tags=["Root"])
def root():
    index_path = Path(__file__).parent / "index.html"
    if not index_path.exists():
        return "<h1>AstroBot</h1><p>index.html non trovato.</p>"
    return index_path.read_text(encoding="utf-8")


print("[DEBUG] main import end")


@app.get("/debug/credits_env")
def debug_credits_env():
    return {
        "SUPABASE_URL": SUPABASE_URL,
        "USE_SUPABASE": USE_SUPABASE,
    }


# ---------------------------------------------------------
# ROUTER SINASTRIA AI (opzionale)
# ---------------------------------------------------------
try:
    from routes.routes_sinastria_ai import router as sinastria_ai_router

    app.include_router(sinastria_ai_router)
    print("[DEBUG] routes_sinastria_ai included")
except Exception as e:
    print(f"[WARN] routes_sinastria_ai non caricato: {e}")
