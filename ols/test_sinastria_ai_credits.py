import os
import json
import time
import requests
from pprint import pprint

# =====================================================
# CONFIG BASE
# =====================================================

BASE_URL = os.getenv("ASTROBOT_BASE_URL", "http://127.0.0.1:8001")

# Usa la variabile d'ambiente TOKEN (quella che hai già usato per tema_ai)
TOKEN = os.getenv("TOKEN")

if not TOKEN:
    raise SystemExit(
        "❌ Variabile d'ambiente TOKEN non impostata.\n"
        "   Esegui prima, in questo terminale:\n"
        '   set TOKEN=eyJhbGciOi... (il tuo JWT)\n'
    )

HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Content-Type": "application/json",
}


def call_sinastria_ai(tier: str) -> dict:
    """
    Chiama /sinastria_ai con tier = 'free' o 'premium'
    e ritorna il JSON della risposta.
    """
    url = f"{BASE_URL}/sinastria_ai"
    body = {
        "A": {
            "citta": "Napoli",
            "data": "1986-07-19",
            "ora": "08:50",
            "nome": "Andrea",
        },
        "B": {
            "citta": "Napoli",
            "data": "1993-02-26",
            "ora": "04:00",
            "nome": "Muo",
        },
        "tier": tier,
    }

    print(f"\n================= SINASTRIA_AI ({tier.upper()}) =================")
    print(f"POST {url}")
    print("Body:")
    print(json.dumps(body, indent=2, ensure_ascii=False))

    t0 = time.time()
    resp = requests.post(url, headers=HEADERS, json=body)
    dt = time.time() - t0

    print(f"\nHTTP {resp.status_code} in {dt:.2f}s")

    try:
        data = resp.json()
    except Exception:
        print("❌ Response non JSON:")
        print(resp.text)
        raise

    print("\n--- RESPONSE RAW (TRONCATA A 1000 CHAR) ---")
    text = json.dumps(data, indent=2, ensure_ascii=False)
    print(text[:1000])
    if len(text) > 1000:
        print("... [TRONCATO] ...")

    return data


def print_billing_block(label: str, resp_json: dict) -> None:
    """
    Stampa il blocco billing se presente nella risposta.
    """
    print(f"\n>>> {label} - BILLING <<<")
    billing = resp_json.get("billing")
    if not billing:
        print("⚠️  Nessun blocco 'billing' nella risposta.")
        return

    pprint(billing)


def main():
    print(f"BASE_URL = {BASE_URL}")
    print("TOKEN presente?:", bool(TOKEN))

    # 1) Test FREE
    try:
        resp_free = call_sinastria_ai("free")
        print_billing_block("SINASTRIA FREE", resp_free)
    except Exception as e:
        print(f"\n❌ Errore nella chiamata FREE: {e}")

    # 2) Test PREMIUM
    try:
        resp_premium = call_sinastria_ai("premium")
        print_billing_block("SINASTRIA PREMIUM", resp_premium)
    except Exception as e:
        print(f"\n❌ Errore nella chiamata PREMIUM: {e}")


if __name__ == "__main__":
    main()
