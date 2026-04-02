from typing import Optional
import os
import uuid

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from pydantic import BaseModel

oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl="token-not-used-here",
    auto_error=False,
)

ISSUER = os.getenv("AUTH_ISSUER", "astrobot-auth-pub")
AUDIENCE = os.getenv("AUTH_AUDIENCE", "chatbot-test")

def _load_public_key() -> bytes:
    pem = os.getenv("AUTH_PUBLIC_KEY_PEM")
    if pem:
        return pem.encode("utf-8")
    path = os.getenv("AUTH_PUBLIC_KEY_PATH", "secrets/jwtRS256.key.pub")
    try:
        return open(path, "rb").read()
    except Exception as e:
        raise RuntimeError(f"Missing public key file at {path}: {e}")

PUBLIC_KEY = _load_public_key()

class UserContext(BaseModel):
    sub: str
    role: str = "free"

def decode_token_verified(token: str) -> UserContext:
    try:
        data = jwt.decode(
            token,
            key=PUBLIC_KEY,
            algorithms=["RS256"],
            issuer=ISSUER,
            audience=AUDIENCE,
            options={
                "require": ["sub", "iss", "aud", "iat", "exp"],
                "verify_exp": True,
            },
            leeway=30,
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired")
    except jwt.PyJWTError as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=f"Invalid token: {e}")

    sub = data.get("sub")
    role = data.get("role", "free") or "free"
    if not sub:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token without sub")

    return UserContext(sub=sub, role=role)

async def get_current_user(
    token: Optional[str] = Depends(oauth2_scheme),
) -> UserContext:
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing token (anonymous login required)",
        )

    return decode_token_verified(token)
