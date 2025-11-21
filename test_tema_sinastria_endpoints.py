"""
Test end-to-end AstroBot (local backend chatbot-test):

- /tema       (free + premium)
- /sinastria  (free + premium)

Usa lo schema reale di /sinastria:

class SinastriaRequest(BaseModel):
    A: Persona
    B: Persona
    scope: str = "sinastria"
    tier: str = "free"

Quindi il body DEVE essere del tipo:

{
  "A": {...},
  "B": {...},
  "scope": "sinastria",
  "tier": "free" | "premium"
}
"""

import os
import json
from dataclasses import dataclass
from typing import Any, Dict, Optional

import requests

# =========================================================
# CONFIG
# =========================================================

BASE_URL = "http://127.0.0.1:8001"

TOKEN_FREE = os.environ.get("TOKEN_FREE")
TOKEN_PREMIUM = os.environ.get("TOKEN_PREMIUM")


@dataclass
class Persona:
    nome: str
    citta: str
    data: str
    ora: str


# Mario: tema natale
P1 = Persona("Mario", "Napoli", "1986-07-19", "08:50")
# Partner per sinastria
P2 = Persona("Partner", "Napoli", "1993-02-26", "04:50")


# =========================================================
# UTILITY
# =========================================================

def _auth_headers(tier: str) -> Dict[str, str]:
    """
    Se esistono TOKEN_FREE / TOKEN_PREMIUM li usa come Authorization Bearer,
    altrimenti nessun header.
    """
    headers: Dict[str, str] = {
        "Content-Type": "application/json",
    }

    token: Optional[str] = None
    if tier == "free":
        token = TOKEN_FREE
    else:
        token = TOKEN_PREMIUM

    if token:
        headers["Authorization"] = f"Bearer {token}"

    return headers


def _print_response_info(label: str, resp: requests.Response, max_preview: int = 2000) -> None:
    text = resp.text
    print(f"\n=== RAW RESPONSE {label} (TRONCATA a {max_preview} char) ===")
    print(text[:max_preview])
    print("=== FINE RAW RESPONSE ===\n")

    try:
        data = resp.json()
        pretty = json.dumps(data, indent=2, ensure_ascii=False)
        print(f"--- RESPONSE {label} (JSON) (TRONCATO a {max_preview} char) ---")
        print(pretty[:max_preview])
        print(f"--- FINE RESPONSE {label} (JSON) (len={len(pretty)}) ---\n")
    except Exception as e:
        print(f"[WARN] impossibile fare json() per {label}: {e}")


# =========================================================
# TEST /tema
# =========================================================

def test_tema():
    url = f"{BASE_URL}/tema"
    print("\n====================== TEST /tema ======================")
    print("Endpoint:", url)
    print("TOKEN_FREE presente?:", bool(TOKEN_FREE))
    print("TOKEN_PREMIUM presente?:", bool(TOKEN_PREMIUM))

    for tier in ("free", "premium"):
        body = {
            "citta": P1.citta,
            "data": P1.data,
            "ora": P1.ora,
            "nome": P1.nome,
            "email": None,
            "domanda": None,
            "scope": "tema",
            "tier": tier,
        }
        body_str = json.dumps(body, ensure_ascii=False)
        print(f"\n=== POST {url} ===")
        print("Dimensione body (char) =", len(body_str))
        print("Body (TRONCATO a 1000 char):")
        print(body_str[:1000])
        print("----- FINE BODY -----")

        try:
            resp = requests.post(url, headers=_auth_headers(tier), data=body_str, timeout=30)
        except Exception as e:
            print("[ERRORE REQUEST]", e)
            continue

        print("HTTP STATUS:", resp.status_code)
        if resp.status_code != 200:
            _print_response_info(f"/tema {tier.upper()} (ERRORE)", resp)
            continue

        _print_response_info(f"/tema {tier.upper()}", resp)


# =========================================================
# TEST /sinastria
# =========================================================

def test_sinastria():
    url = f"{BASE_URL}/sinastria"
    print("\n================== TEST /sinastria =====================")
    print("Endpoint:", url)

    for tier in ("free", "premium"):
        body = {
            # ⚠️ schema reale: A e B, non persona1/persona2
            "A": {
                "nome": P1.nome,
                "citta": P1.citta,
                "data": P1.data,
                "ora": P1.ora,
            },
            "B": {
                "nome": P2.nome,
                "citta": P2.citta,
                "data": P2.data,
                "ora": P2.ora,
            },
            "scope": "sinastria",
            "tier": tier,
        }

        body_str = json.dumps(body, ensure_ascii=False)
        print(f"\n=== POST {url} ===")
        print("Dimensione body (char) =", len(body_str))
        print("Body (TRONCATO a 1000 char):")
        print(body_str[:1000])
        print("----- FINE BODY -----")

        try:
            resp = requests.post(url, headers=_auth_headers(tier), data=body_str, timeout=60)
        except Exception as e:
            print("[ERRORE REQUEST]", e)
            continue

        print("HTTP STATUS:", resp.status_code)
        _print_response_info(f"/sinastria {tier.upper()}", resp)

        if resp.status_code == 200:
            try:
                data = resp.json()
            except Exception:
                data = {}

            # piccole metriche utili
            sinastria = data.get("sinastria", {})
            grafico = data.get("grafico_polare", {})
            png_b64 = data.get("png_base64", "")

            aspetti = sinastria.get("aspetti", [])
            print(f"[INFO sinastria {tier}] n_aspetti =", len(aspetti))
            print(f"[INFO sinastria {tier}] grafico_polare keys =", list(grafico.keys()))
            print(f"[INFO sinastria {tier}] png_base64 length =", len(png_b64))


    print("========================================================\n")


# =========================================================
# MAIN
# =========================================================

def main():
    print("=== TEST ASTROBOT: /tema + /sinastria (FREE vs PREMIUM) ===")
    print("BASE_URL:", BASE_URL)
    print("TOKEN_FREE presente?:", bool(TOKEN_FREE))
    print("TOKEN_PREMIUM presente?:", bool(TOKEN_PREMIUM))

    test_tema()
    test_sinastria()

    print("\n=== FINE TEST ===")


if __name__ == "__main__":
    main()
