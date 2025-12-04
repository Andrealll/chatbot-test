# ratelimit.py
import os
from fastapi import Request, HTTPException
import aioredis

REDIS_URL = os.getenv("REDIS_URL")  # es: rediss://:pwd@host:port
redis = None

async def rl_startup():
    """
    Inizializza connessione Redis solo se REDIS_URL è settata.
    """
    global redis
    if REDIS_URL and not isinstance(redis, aioredis.client.Redis):
        redis = await aioredis.from_url(
            REDIS_URL,
            encoding="utf-8",
            decode_responses=True
        )

async def ratelimit(request: Request, limit:int=30, window_sec:int=60):
    """
    Semplice rate limit per IP: max `limit` richieste ogni `window_sec` secondi.
    Se REDIS_URL non è impostata, non applica il limite.
    """
    if not redis:
        return
    ip = request.client.host
    key = f"rl:{ip}"
    cnt = await redis.incr(key)
    if cnt == 1:
        await redis.expire(key, window_sec)
    if cnt > limit:
        raise HTTPException(429, "Troppo traffico. Riprova tra poco.")
