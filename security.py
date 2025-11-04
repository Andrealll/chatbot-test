# security.py
import os
import uuid
import hashlib
from fastapi import Request, Response

IP_SALT = os.getenv("IP_SALT", "changeme-long-random-string")

def ip_hash(ip: str) -> str:
    """
    Hash dell'IP con salt per evitare di salvare l'IP in chiaro.
    """
    return hashlib.sha256((IP_SALT + (ip or "")).encode()).hexdigest()

def get_guest_id(request: Request, response: Response) -> str:
    """
    Ritorna guest_id dal cookie, o lo crea e lo imposta se non presente.
    """
    gid = request.cookies.get("guest_id")
    if not gid:
        gid = str(uuid.uuid4())
        # Cookie httpOnly, durata 180 giorni, samesite Lax
        response.set_cookie(
            "guest_id",
            gid,
            max_age=60*60*24*180,
            httponly=True,
            samesite="Lax"
        )
    return gid
