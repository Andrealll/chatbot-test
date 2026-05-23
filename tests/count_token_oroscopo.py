import json
import requests

API_BASE = "http://127.0.0.1:8001"
TOKEN = "eyJhbGciOiJSUzI1NiIsImtpZCI6ImsxIiwidHlwIjoiSldUIn0.eyJzdWIiOiJhbm9uLTdjMzEzZTgyLTU2MmItNDZmNC1hNjgyLTM2MzIzY2MwYmRhYyIsInJvbGUiOiJmcmVlIiwiaXNzIjoiYXN0cm9ib3QtYXV0aC1wdWIiLCJhdWQiOiJjaGF0Ym90LXRlc3QiLCJpYXQiOjE3NzkxODM1MTUsImV4cCI6MTc3OTE4NzExNX0.YQTfvoGgmbYR0PSQu95JxmXT7MiDa_N6YMJ1gdMbQEQJpxAf4-z88sxZnuf54Lqevhh0GSyrxrurZ_SG3aH-h7tZ5-sPe5nPSTaoJDk5z6qS1gWXPCdNKM7ghdSSrw0v-Vi3o97rx1LbTw3JGWnPAA48vQ3M9xdf6_mE4O_k5SF7yv04CPvfsxrdG-PZxFIms4DOPwcas-b1h-JK6ELEaDeR_a5dGzhrJmJ7_DWOweTpTfeFdH4qq0fOdNrp--SqPi0--X0O5WQCoob75BwLRZNbyFJdS2p0CoW5yeU0vpOXwIxNhqJKaK_v0CO3_hopqzD4WrTIwe_JAMk7ZvIIug"
INTERNAL_SECRET = "fdishgfadflhbdjknkgsfppretlalashdfkasjzkxzmnvxcnbureityeuynfjkdsnkl"

BASE_PAYLOAD = {
    "citta": "Napoli",
    "data": "1986-07-19",
    "ora": "08:50",
    "nome": "Andrea",
    "lang": "it",
    "window_mode": "rolling",
}

def count_tokens(obj):
    text = json.dumps(obj, ensure_ascii=False)
    try:
        import tiktoken
        enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text))
    except Exception:
        return round(len(text) / 4)

def call_free(scope):
    payload = dict(BASE_PAYLOAD)
    payload["tier"] = "free"

    r = requests.post(
        f"{API_BASE}/oroscopo_ai/{scope}",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {TOKEN}",
        },
        json=payload,
        timeout=180,
    )
    return r

def call_premium_guest(scope, window_mode="rolling", target_year=None):
    payload = dict(BASE_PAYLOAD)
    payload["tier"] = "premium"
    payload["window_mode"] = window_mode

    if target_year:
        payload["target_year"] = target_year

    body = {
        "order_id": f"test_{scope}_premium_tokens",
        "email": "test@dyana.app",
        "payload": payload,
    }

    r = requests.post(
        f"{API_BASE}/oroscopo_ai/internal/guest/{scope}",
        headers={
            "Content-Type": "application/json",
            "x-internal-secret": INTERNAL_SECRET,
        },
        json=body,
        timeout=180,
    )
    return r

def extract_row(scope, tier, mode, response):
    try:
        data = response.json()
    except Exception:
        return {
            "scope": scope,
            "tier": tier,
            "mode": mode,
            "status": "JSON_ERROR",
            "http_status": response.status_code,
            "error": response.text[:300],
        }

    payload_ai = data.get("payload_ai") or {}
    pipe = ((data.get("engine_result") or {}).get("pipe") or {})
    plan = pipe.get("period_plan") or {}

    oroscopo_ai = data.get("oroscopo_ai") or {}
    ai_debug = {}
    if isinstance(oroscopo_ai, dict):
        ai_debug = oroscopo_ai.get("_ai_debug") or oroscopo_ai.get("_ai_usage") or {}

    return {
        "scope": scope,
        "tier": tier,
        "mode": mode,
        "status": data.get("status"),
        "http_status": response.status_code,
        "payload_tokens_est": count_tokens(payload_ai),
        "payload_chars": len(json.dumps(payload_ai, ensure_ascii=False)),
        "ai_input_tokens": ai_debug.get("input_tokens"),
        "ai_output_tokens": ai_debug.get("output_tokens"),
        "model": ai_debug.get("model"),
        "period_count": len(plan.get("sottoperiodi") or []),
        "snapshot_count": len(plan.get("snapshots") or []),
        "date_start": (plan.get("date_range") or {}).get("start"),
        "date_end": (plan.get("date_range") or {}).get("end"),
        "error": data.get("error"),
    }

def main():
    rows = []

    for scope in ["daily", "weekly", "monthly"]:
        print(f"TEST FREE {scope}")
        r = call_free(scope)
        rows.append(extract_row(scope, "free", "rolling", r))

    for scope in ["daily", "weekly", "monthly"]:
        print(f"TEST PREMIUM {scope}")
        r = call_premium_guest(scope, "rolling")
        rows.append(extract_row(scope, "premium", "rolling", r))


    print("\nRISULTATI")
    print(json.dumps(rows, ensure_ascii=False, indent=2))

    with open("oroscopo_token_report.json", "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)

    print("\nFile scritto: oroscopo_token_report.json")

if __name__ == "__main__":
    main()