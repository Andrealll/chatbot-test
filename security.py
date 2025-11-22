# security.py (locale con .env)
import os, uuid, datetime as dt
import jwt
from fastapi import HTTPException, Header, status
from dotenv import load_dotenv
from pathlib import Path

load_dotenv()  # carica .env

PRIV_PATH = os.getenv("JWT_PRIVATE_KEY_PATH", "jwt_private.pem")
PUB_PATH  = os.getenv("JWT_PUBLIC_KEY_PATH", "jwt_public.pem")

JWT_PRIVATE = Path(PRIV_PATH).read_text(encoding="utf-8") if Path(PRIV_PATH).exists() else None
JWT_PUBLIC  = Path(PUB_PATH).read_text(encoding="utf-8")  if Path(PUB_PATH).exists() else None

JWT_ISS = os.getenv("JWT_ISS", "astrobot-auth-pub")
JWT_AUD = os.getenv("JWT_AUD", "chatbot-test")
JWT_ALG = os.getenv("JWT_ALG", "RS256")

def sign_jwt(sub: str, role: str, name: str | None = None, email: str | None = None, ttl_hours: int = 6) -> str:
    if not JWT_PRIVATE:
        raise RuntimeError("JWT_PRIVATE_KEY_PEM non configurata (manca il file?)")
    now = dt.datetime.utcnow()
    payload = {
        "iss": JWT_ISS,
        "aud": JWT_AUD,
        "sub": sub,
        "role": role,
        "name": name,
        "email": email,
        "iat": int(now.timestamp()),
        "exp": int((now + dt.timedelta(hours=ttl_hours)).timestamp()),
        "jti": str(uuid.uuid4()),
    }
    headers = {"kid": "k1", "typ": "JWT"}
    return jwt.encode(payload, JWT_PRIVATE, algorithm=JWT_ALG, headers=headers)

def verify_jwt(token: str) -> dict:
    if not JWT_PUBLIC:
        raise HTTPException(status_code=500, detail="JWT_PUBLIC_KEY_PEM non configurata (manca il file?)")
    try:
        return jwt.decode(
            token,
            JWT_PUBLIC,
            algorithms=[JWT_ALG],
            audience=JWT_AUD,
            issuer=JWT_ISS,
            options={"require": ["exp", "iat", "iss", "aud", "sub"]},
        )
    except jwt.PyJWTError as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=f"Invalid token: {e}")

def get_user_context_optional(authorization: str | None = Header(None)) -> dict:
    if not authorization or not authorization.lower().startswith("bearer "):
        return {"sub": "anon", "role": "free"}
    token = authorization.split(" ", 1)[1].strip()
    claims = verify_jwt(token)
    return {"sub": claims["sub"], "role": claims.get("role", "free"), "claims": claims}

def get_user_context_required(authorization: str | None = Header(None)) -> dict:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing Bearer token")
    token = authorization.split(" ", 1)[1].strip()
    claims = verify_jwt(token)
    return {"sub": claims["sub"], "role": claims.get("role", "free"), "claims": claims}
