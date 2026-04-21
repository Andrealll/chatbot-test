import os
from datetime import datetime, timezone

import httpx

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
RESEND_API_KEY = os.getenv("RESEND_API_KEY")
RESEND_FROM = os.getenv("RESEND_FROM", "DYANA <noreply@dyana.app>")


def require_env() -> None:
    missing = [
        name for name, value in {
            "SUPABASE_URL": SUPABASE_URL,
            "SUPABASE_SERVICE_ROLE_KEY": SUPABASE_SERVICE_ROLE_KEY,
            "RESEND_API_KEY": RESEND_API_KEY,
            "RESEND_FROM": RESEND_FROM,
        }.items() if not value
    ]
    if missing:
        raise RuntimeError(f"Missing env: {', '.join(missing)}")


def supabase_headers() -> dict:
    return {
        "apikey": SUPABASE_SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
        "Content-Type": "application/json",
    }


def resend_headers() -> dict:
    return {
        "Authorization": f"Bearer {RESEND_API_KEY}",
        "Content-Type": "application/json",
    }


def build_welcome_email(lang: str) -> dict:
    if lang == "it":
        return {
            "subject": "Benvenuta/o in DYANA ✨",
            "html": """
                <p>Ciao,</p>
                <p>benvenuta/o in <strong>DYANA</strong>.</p>
                <p>Qui trovi contenuti astrologici personalizzati costruiti sui tuoi dati reali.</p>
                <p>Per iniziare, entra qui:</p>
                <p><a href="https://dyana.app/tema">Apri il tuo tema su DYANA</a></p>
                <p>A presto,<br>DYANA</p>
            """,
            "text": (
                "Ciao,\n\n"
                "benvenuta/o in DYANA.\n"
                "Qui trovi contenuti astrologici personalizzati costruiti sui tuoi dati reali.\n\n"
                "Per iniziare: https://dyana.app/tema\n\n"
                "A presto,\nDYANA"
            ),
        }

    return {
        "subject": "Welcome to DYANA ✨",
        "html": """
            <p>Hi,</p>
            <p>welcome to <strong>DYANA</strong>.</p>
            <p>Here you will find personalized astrology content built on your real birth data.</p>
            <p>Start here:</p>
            <p><a href="https://dyana.app/en/tema">Open your chart on DYANA</a></p>
            <p>See you soon,<br>DYANA</p>
        """,
        "text": (
            "Hi,\n\n"
            "welcome to DYANA.\n"
            "Here you will find personalized astrology content built on your real birth data.\n\n"
            "Start here: https://dyana.app/en/tema\n\n"
            "See you soon,\nDYANA"
        ),
    }


async def call_rpc(client: httpx.AsyncClient, fn_name: str) -> None:
    url = f"{SUPABASE_URL}/rest/v1/rpc/{fn_name}"
    resp = await client.post(url, headers=supabase_headers(), json={})
    if resp.status_code not in (200, 204):
        raise RuntimeError(f"RPC {fn_name} failed: {resp.status_code} {resp.text}")


async def fetch_candidates(client: httpx.AsyncClient, limit: int = 200) -> list[dict]:
    url = f"{SUPABASE_URL}/rest/v1/v_welcome_email_candidates"
    params = {
        "select": "user_id,email,lang,created_at",
        "order": "created_at.asc",
        "limit": str(limit),
    }
    resp = await client.get(url, headers=supabase_headers(), params=params)
    if resp.status_code != 200:
        raise RuntimeError(f"fetch candidates failed: {resp.status_code} {resp.text}")
    return resp.json()


async def send_welcome_email(client: httpx.AsyncClient, email: str, lang: str) -> None:
    payload = build_welcome_email(lang)

    resp = await client.post(
        "https://api.resend.com/emails",
        headers=resend_headers(),
        json={
            "from": RESEND_FROM,
            "to": [email],
            "subject": payload["subject"],
            "html": payload["html"],
            "text": payload["text"],
        },
    )
    if resp.status_code not in (200, 201):
        raise RuntimeError(f"Resend send failed: {resp.status_code} {resp.text}")


async def mark_sent(client: httpx.AsyncClient, user_id: str) -> None:
    url = f"{SUPABASE_URL}/rest/v1/user_marketing_profile"
    now_iso = datetime.now(timezone.utc).isoformat()
    resp = await client.patch(
        url,
        headers={**supabase_headers(), "Prefer": "return=minimal"},
        params={"user_id": f"eq.{user_id}"},
        json={
            "welcome_email_sent_at": now_iso,
            "welcome_email_status": "sent",
            "welcome_email_error": None,
            "updated_at": now_iso,
        },
    )
    if resp.status_code not in (200, 204):
        raise RuntimeError(f"mark_sent failed: {resp.status_code} {resp.text}")


async def mark_error(client: httpx.AsyncClient, user_id: str, error_msg: str) -> None:
    url = f"{SUPABASE_URL}/rest/v1/user_marketing_profile"
    now_iso = datetime.now(timezone.utc).isoformat()
    resp = await client.patch(
        url,
        headers={**supabase_headers(), "Prefer": "return=minimal"},
        params={"user_id": f"eq.{user_id}"},
        json={
            "welcome_email_status": "error",
            "welcome_email_error": error_msg[:1000],
            "updated_at": now_iso,
        },
    )
    if resp.status_code not in (200, 204):
        raise RuntimeError(f"mark_error failed: {resp.status_code} {resp.text}")


async def run_welcome_batch(limit: int = 200) -> dict:
    require_env()

    async with httpx.AsyncClient(timeout=30.0) as client:
        # allinea profilo marketing + lingue prima del batch
        await call_rpc(client, "sync_all_marketing_profile_from_auth_users")
        await call_rpc(client, "sync_missing_user_marketing_lang")

        candidates = await fetch_candidates(client, limit=limit)

        sent = 0
        errors = 0

        for row in candidates:
            user_id = row["user_id"]
            email = row["email"]
            lang = row.get("lang") or "en"

            try:
                await send_welcome_email(client, email=email, lang=lang)
                await mark_sent(client, user_id=user_id)
                sent += 1
            except Exception as e:
                await mark_error(client, user_id=user_id, error_msg=str(e))
                errors += 1

        return {
            "candidates": len(candidates),
            "sent": sent,
            "errors": errors,
        }


if __name__ == "__main__":
    import asyncio
    result = asyncio.run(run_welcome_batch(limit=200))
    print(result)