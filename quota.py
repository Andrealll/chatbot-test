# quota.py
from datetime import datetime
from fastapi import Request, Response, HTTPException

from security import get_guest_id, ip_hash
from ratelimit import ratelimit

# Quante chiamate gratuite al giorno per guest (senza login)
GUEST_DAILY_QUOTA = 3

# Elenco delle feature libere (senza login)
FREE_METHODS = {"demo_transito_oggi", "demo_tema_anteprima"}

async def enforce_guest_quota(
    request: Request,
    response: Response,
    supabase,           # Client Supabase passato dal main
    feature: str,
):
    """
    Applica rate-limit IP + quota giornaliera per guest_id su funzioni free.
    Crea la riga guests se non esiste, resetta il contatore ogni giorno UTC.
    """
    if feature not in FREE_METHODS:
        raise HTTPException(401, "Login richiesto")

    # Rate-limit IP (anti-abuso)
    await ratelimit(request, limit=30, window_sec=60)

    gid = get_guest_id(request, response)
    ip_h = ip_hash(request.client.host)
    ua = request.headers.get("User-Agent", "")[:180]

    today = datetime.utcnow().date().isoformat()

    row = supabase.table("guests").select("*").eq("guest_id", gid).single().execute().data

    if not row:
        supabase.table("guests").insert({
            "guest_id": gid,
            "day": today,
            "free_uses": 0,
            "last_seen": datetime.utcnow().isoformat(),
            "ip_hash": ip_h,
            "ua": ua
        }).execute()
        free_uses, day = 0, today
    else:
        free_uses = row.get("free_uses", 0)
        day = row.get("day", today)

    # reset giornaliero
    if day != today:
        free_uses = 0
        supabase.table("guests").update({
            "free_uses": 0, "day": today
        }).eq("guest_id", gid).execute()

    if free_uses >= GUEST_DAILY_QUOTA:
        raise HTTPException(
            402,
            detail={"message": "Hai raggiunto il limite gratuito di oggi. Accedi per sbloccare di più."}
        )

    # incrementa conteggio
    supabase.table("guests").update({
        "free_uses": free_uses + 1,
        "last_seen": datetime.utcnow().isoformat(),
        "ip_hash": ip_h,
        "ua": ua
    }).eq("guest_id", gid).execute()

    return gid
