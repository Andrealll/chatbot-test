import requests
import json

# Endpoint del backend già deployato su Render
URL = "https://chatbot-test-0h4o.onrender.com/oroscopo"

# Tema "stub" minimale: giusto per soddisfare lo schema del backend.
# Poi lo sostituiremo con il vero oroscopo_struct / payload_ai.
tema_stub = {
    "meta": {
        "nome": "Andrea",
        "citta": "Napoli",
        "data_nascita": "1986-07-19",
        "ora_nascita": "08:50",
        "tier": "premium",
        "lang": "it",
        "scope": "oroscopo_ai"
    },
    # puoi aggiungere altro dopo (tema, transiti, periodi...)
}

payload = {
    "scope": "oroscopo_ai",
    "tier": "premium",         # "free" o "premium"
    "periodo": "mensile",      # "giornaliero" / "settimanale" / "mensile" / "annuale"
    "tema": tema_stub,         # 👈 CAMPO RICHIESTO DAL BACKEND
    # questi campi extra, se li lasci, verranno ignorati dal modello Pydantic
    "nome": "Andrea",
    "citta": "Napoli",
    "data": "1986-07-19",
    "ora": "08:50",
}

print("\n[AstroBot → Render → Groq] Invio payload a backend...")
print(json.dumps(payload, indent=2, ensure_ascii=False))

resp = requests.post(URL, json=payload)
print("\n[STATUS]", resp.status_code)

try:
    data = resp.json()
    print("\n[RISPOSTA BACKEND]:\n")
    print(json.dumps(data, indent=2, ensure_ascii=False))
except Exception:
    print("\n[RISPOSTA RAW]:")
    print(resp.text)
