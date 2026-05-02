import os
import asyncio
from pathlib import Path
from datetime import datetime, timezone

import httpx
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
RESEND_KEY = os.getenv("RESEND_API_KEY")
FROM_EMAIL = os.getenv("RESEND_FROM_EMAIL")

SEG_OPTIN_IT = os.getenv("RESEND_SEGMENT_OPTIN_IT")
SEG_OPTIN_EN = os.getenv("RESEND_SEGMENT_OPTIN_EN")

WELCOME_DRY_RUN = os.getenv("WELCOME_DRY_RUN", "1") == "1"


def require_env():
    missing = [
        k for k, v in {
            "SUPABASE_URL": SUPABASE_URL,
            "SUPABASE_SERVICE_ROLE_KEY": SUPABASE_KEY,
            "RESEND_API_KEY": RESEND_KEY,
            "RESEND_FROM_EMAIL": FROM_EMAIL,
            "RESEND_SEGMENT_OPTIN_IT": SEG_OPTIN_IT,
            "RESEND_SEGMENT_OPTIN_EN": SEG_OPTIN_EN,
        }.items()
        if not v
    ]
    if missing:
        raise RuntimeError(f"Missing env: {', '.join(missing)}")


def sb_headers():
    return {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
    }


def resend_headers():
    return {
        "Authorization": f"Bearer {RESEND_KEY}",
        "Content-Type": "application/json",
    }


def norm_lang(value):
    if isinstance(value, dict):
        value = value.get("value") or value.get("text") or value.get("name")
    v = str(value or "").strip().lower()
    return v if v in ("it", "en") else None


async def resend_request(client, method, url, **kwargs):
    for attempt in range(6):
        r = await client.request(method, url, headers=resend_headers(), **kwargs)
        if r.status_code != 429:
            return r
        await asyncio.sleep(4 + attempt)
    return r


async def get_resend_contact(client, email):
    r = await resend_request(client, "GET", f"https://api.resend.com/contacts/{email}")
    if r.status_code == 404:
        return None
    r.raise_for_status()
    return r.json()


async def fetch_profiles(client):
    r = await client.get(
        f"{SUPABASE_URL}/rest/v1/user_marketing_profile",
        headers=sb_headers(),
        params={
            "select": "user_id,email,lang,marketing_consent,marketing_consent_updated_at,is_deleted,welcome_email_status,welcome_email_sent_at,updated_at",
            "email": "not.is.null",
            "limit": "1000",
        },
    )
    r.raise_for_status()
    return r.json()


async def fetch_welcome_candidates(client):
    r = await client.get(
        f"{SUPABASE_URL}/rest/v1/user_marketing_profile",
        headers=sb_headers(),
        params={
            "select": "user_id,email,lang,marketing_consent,is_deleted,welcome_email_status,welcome_email_sent_at,updated_at",
            "email": "not.is.null",
            "limit": "1000",
        },
    )

    print("WELCOME_URL", str(r.request.url))
    print("WELCOME_STATUS", r.status_code)

    r.raise_for_status()
    rows = r.json()

    candidates = []
    for x in rows:
        email = str(x.get("email") or "")
        status = x.get("welcome_email_status")

        if x.get("is_deleted") is not False:
            continue
        if x.get("marketing_consent") is not True:
            continue
        if not email or email.startswith("deleted_"):
            continue
        if x.get("lang") not in ("it", "en"):
            continue
        if x.get("welcome_email_sent_at") is not None:
            continue
        if status == "sent":
            continue

        candidates.append(x)

    candidates.sort(key=lambda x: str(x.get("updated_at") or ""), reverse=True)

    print("WELCOME_CANDIDATES", len(candidates))
    print("WELCOME_EMAILS", [x["email"] for x in candidates[:100]])

    return candidates


def build_contact_payload(row, resend_contact=None):
    now = datetime.now(timezone.utc).isoformat()
    old_props = (resend_contact or {}).get("properties") or {}

    is_deleted = bool(row.get("is_deleted"))
    consent = bool(row.get("marketing_consent", True))
    lang = norm_lang(row.get("lang")) or norm_lang(old_props.get("lang"))
    welcome_sent = 1 if row.get("welcome_email_status") == "sent" or row.get("welcome_email_sent_at") else 0

    props = {
        "marketing_consent": 0 if is_deleted else (1 if consent else 0),
        "marketing_consent_updated_at": row.get("marketing_consent_updated_at") or now,
        "is_deleted": 1 if is_deleted else 0,
        "welcome_sent": welcome_sent,
    }

    if lang:
        props["lang"] = lang

    return {
        "email": row["email"],
        "unsubscribed": True if is_deleted else not consent,
        "properties": props,
    }, lang, is_deleted, consent


async def upsert_contact(client, row):
    email = row["email"]
    resend_contact = await get_resend_contact(client, email)

    if row.get("is_deleted") and resend_contact is None:
        return False, None, "skipped_deleted_missing"

    payload, lang, is_deleted, consent = build_contact_payload(row, resend_contact)

    r = await resend_request(
        client,
        "POST",
        "https://api.resend.com/contacts",
        json=payload,
    )

    if r.status_code in (200, 201):
        return True, lang, "created"

    if r.status_code in (409, 422):
        r = await resend_request(
            client,
            "PATCH",
            f"https://api.resend.com/contacts/{email}",
            json={
                "unsubscribed": payload["unsubscribed"],
                "properties": payload["properties"],
            },
        )

        if r.status_code in (200, 201):
            return True, lang, "updated"

        if r.status_code == 404:
            return False, lang, "skipped_missing_after_conflict"

    raise RuntimeError(f"upsert failed {email}: {r.status_code} {r.text}")


async def add_optin_segment(client, email, lang):
    seg = SEG_OPTIN_IT if lang == "it" else SEG_OPTIN_EN if lang == "en" else None
    if not seg:
        return False

    r = await resend_request(
        client,
        "POST",
        f"https://api.resend.com/contacts/{email}/segments/{seg}",
    )

    if r.status_code in (200, 201, 204, 409):
        return True

    raise RuntimeError(f"segment failed {email}: {r.status_code} {r.text}")


def welcome_copy(lang):
    if lang == "it":
        return {
            "subject": "Il tuo spazio DYANA è attivo",
            "html": """
<p>Ciao,</p>
<p>il tuo spazio su DYANA è attivo.</p>
<p>Puoi:</p>
<ul>
  <li>✨ esplorare il tuo <b>Tema Natale</b></li>
  <li>🔮 leggere il tuo <b>oroscopo aggiornato ogni giorno</b></li>
  <li>💞 scoprire la tua <b>compatibilità con un’altra persona</b></li>
</ul>
<p>👉 <a href="https://dyana.app/it/tema">Vai al tuo Tema</a></p>
<p>Ogni giorno hai accesso a contenuti aggiornati e puoi consultare il tuo oroscopo completo.</p>
<p>Sono disponibili crediti gratuiti per sbloccare le letture più approfondite.</p>
""",
        }

    return {
        "subject": "Your DYANA space is active",
        "html": """
<p>Hi,</p>
<p>your DYANA space is now active.</p>
<p>You can:</p>
<ul>
  <li>✨ explore your <b>Birth Chart</b></li>
  <li>🔮 read your <b>updated daily horoscope</b></li>
  <li>💞 discover your <b>compatibility with someone</b></li>
</ul>
<p>👉 <a href="https://dyana.app/en/tema">Go to your chart</a></p>
<p>You can come back every day to check your full horoscope.</p>
<p>Free credits are available to unlock deeper readings.</p>
""",
    }


async def mark_welcome(client, user_id, status, error=None):
    now = datetime.now(timezone.utc).isoformat()

    payload = {
        "welcome_email_status": status,
        "welcome_email_error": error,
        "updated_at": now,
    }

    if status == "sent":
        payload["welcome_email_sent_at"] = now

    r = await client.patch(
        f"{SUPABASE_URL}/rest/v1/user_marketing_profile?user_id=eq.{user_id}",
        headers={**sb_headers(), "Prefer": "return=minimal"},
        json=payload,
    )
    r.raise_for_status()


async def send_welcome(client, row):
    copy = welcome_copy(row["lang"])

    return await resend_request(
        client,
        "POST",
        "https://api.resend.com/emails",
        json={
            "from": FROM_EMAIL,
            "to": [row["email"]],
            "subject": copy["subject"],
            "html": copy["html"],
        },
    )


async def main():
    require_env()

    result = {
        "synced": 0,
        "segmented": 0,
        "sync_skipped": 0,
        "sync_errors": 0,
        "welcome_candidates": 0,
        "welcome_sent": 0,
        "welcome_errors": 0,
        "dry_run": WELCOME_DRY_RUN,
    }

    async with httpx.AsyncClient(timeout=45) as client:
        profiles = await fetch_profiles(client)

        for row in profiles:
            try:
                ok, lang, status = await upsert_contact(client, row)

                if ok:
                    result["synced"] += 1

                    if (
                        bool(row.get("marketing_consent", True))
                        and not bool(row.get("is_deleted"))
                        and lang
                    ):
                        added = await add_optin_segment(client, row["email"], lang)
                        if added:
                            result["segmented"] += 1
                else:
                    result["sync_skipped"] += 1

            except Exception as e:
                print("SYNC_ERROR", row.get("email"), str(e))
                result["sync_errors"] += 1

            await asyncio.sleep(2.0)

        candidates = await fetch_welcome_candidates(client)
        result["welcome_candidates"] = len(candidates)

        for row in candidates:
            try:
                ok, lang, status = await upsert_contact(client, row)

                if not ok:
                    print("WELCOME_UPSERT_SKIP", row["email"], status)
                    if not WELCOME_DRY_RUN:
                        await mark_welcome(client, row["user_id"], "error", status)
                    result["welcome_errors"] += 1
                    continue

                if WELCOME_DRY_RUN:
                    print("DRY_RUN_WELCOME", row["lang"], row["email"])
                    continue

                r = await send_welcome(client, row)

                if r.status_code in (200, 201):
                    await mark_welcome(client, row["user_id"], "sent")
                    result["welcome_sent"] += 1
                else:
                    await mark_welcome(client, row["user_id"], "error", r.text)
                    result["welcome_errors"] += 1

            except Exception as e:
                print("WELCOME_ERROR", row.get("email"), str(e))
                if not WELCOME_DRY_RUN:
                    await mark_welcome(client, row["user_id"], "error", str(e))
                result["welcome_errors"] += 1

            await asyncio.sleep(2.0)

    print(result)


if __name__ == "__main__":
    asyncio.run(main())