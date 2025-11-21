from typing import Optional

import base64
import json
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from pydantic import BaseModel

# FastAPI leggerà il Bearer token da Authorization: Bearer <token>
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token-not-used-here")


class UserContext(BaseModel):
    sub: str
    role: str = "free"


def _decode_segment(seg: str) -> bytes:
    """
    Decodifica una singola parte base64url di un JWT (header/payload).
    Aggiunge il padding '=' se necessario.
    """
    padding = "=" * (-len(seg) % 4)
    return base64.urlsafe_b64decode(seg + padding)


def decode_token(token: str) -> UserContext:
    """
    Decodifica il JWT emesso da astrobot_auth SENZA verificare la firma.

    Ci interessa solo leggere:
      - sub  -> identificativo utente
      - role -> "free" | "premium"
    """
    # 1) Controllo formato base del token
    try:
        header_b64, payload_b64, sig_b64 = token.split(".")
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token non valido (formato)",
        )

    # 2) Decodifica del payload
    try:
        payload_bytes = _decode_segment(payload_b64)
        data = json.loads(payload_bytes.decode("utf-8"))
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token non valido (payload)",
        )

    sub = data.get("sub")
    role = data.get("role", "free")

    if not sub:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token senza 'sub'",
        )

    return UserContext(sub=sub, role=role)


async def get_current_user(token: str = Depends(oauth2_scheme)) -> UserContext:
    """
    Dependency FastAPI: estrae l'utente corrente dal token Bearer.
    """
    return decode_token(token)
