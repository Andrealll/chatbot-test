from typing import Optional
import os
import logging

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from pydantic import BaseModel

logger = logging.getLogger(__name__)

oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl="token-not-used-here",
    auto_error=False,
)

ISSUER = os.getenv("AUTH_ISSUER", "astrobot-auth-pub")
AUDIENCE = os.getenv("AUTH_AUDIENCE", "chatbot-test")


def _load_public_key() -> bytes:
    pem = os.getenv("AUTH_PUBLIC_KEY_PEM")
    if pem:
        logger.info("[AUTH] PEM WRAP PATCH ACTIVE")

        normalized = pem.replace("\\n", "\n").strip()

        if "BEGIN PUBLIC KEY" not in normalized:
            normalized = (
                "-----BEGIN PUBLIC KEY-----\n"
                + normalized
                + "\n-----END PUBLIC KEY-----"
            )

        lines = normalized.splitlines()
        logger.info("[AUTH] using AUTH_PUBLIC_KEY_PEM")
        logger.info("[AUTH] literal_backslash_n=%s", "\\n" in pem)
        logger.info("[AUTH] first_line=%r", lines[0] if lines else None)
        logger.info("[AUTH] last_line=%r", lines[-1] if lines else None)
        logger.info("[AUTH] line_count=%s", len(lines))
        logger.info("[AUTH] total_len=%s", len(normalized))

        return normalized.encode("utf-8")

    path = os.getenv("AUTH_PUBLIC_KEY_PATH", "secrets/jwtRS256.key.pub")
    logger.info("[AUTH] using AUTH_PUBLIC_KEY_PATH=%r", path)

    try:
        raw = open(path, "rb").read()
        try:
            txt = raw.decode("utf-8", errors="ignore").strip()
            lines = txt.splitlines()
            logger.info("[AUTH] file_first_line=%r", lines[0] if lines else None)
            logger.info("[AUTH] file_last_line=%r", lines[-1] if lines else None)
            logger.info("[AUTH] file_line_count=%s", len(lines))
            logger.info("[AUTH] file_total_len=%s", len(txt))
        except Exception as log_err:
            logger.warning("[AUTH] unable to inspect public key file: %r", log_err)

        return raw
    except Exception as e:
        raise RuntimeError(f"Missing public key file at {path}: {e}")


class UserContext(BaseModel):
    sub: str
    role: str = "free"


def decode_token_verified(token: str) -> UserContext:
    public_key = _load_public_key()

    try:
        data = jwt.decode(
            token,
            key=public_key,
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
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token expired",
        )
    except jwt.PyJWTError as e:
        logger.exception("[AUTH] JWT decode error")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {e}",
        )

    sub = data.get("sub")
    role = data.get("role", "free") or "free"

    if not sub:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token without sub",
        )

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