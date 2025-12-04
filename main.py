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
    from routes.routes_diyana  import router as diyana_router

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
