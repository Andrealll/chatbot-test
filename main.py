from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
import json

app = FastAPI()

# 🔐 CORS (permette chiamate da Typebot e dal tuo sito)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # puoi restringerlo a domini specifici più avanti
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def home():
    return {"status": "ok", "message": "Backend attivo!"}

@app.post("/run")
async def run(request: Request):
    data = await request.json()
    name = data.get("name", "utente")
    user_input = data.get("input", "nessun input")

    # --- qui potrai eseguire il tuo codice ---
    result = f"Analisi completata per {name}: '{user_input}'."

    # --- eventualmente arricchisci con GPT, codice ecc. ---
    return {
        "status": "ok",
        "response": result,
        "extras": {"version": "beta-1"}
    }
