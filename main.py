from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
import json
from calcoli import calcola_pianeti_da_df, df_tutti

app = FastAPI(title="Chatbot Backend - Pianeti", version="1.0")

# 🔐 CORS: consenti chiamate dal tuo sito o Typebot
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # puoi restringerlo dopo
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

    giorno = int(data.get("giorno", 1))
    mese = int(data.get("mese", 1))
    anno = int(data.get("anno", 2000))

    try:
        valori_raw, valori_norm = calcola_pianeti_da_df(df_tutti, giorno, mese, anno)
        return {
            "status": "ok",
            "giorno": giorno,
            "mese": mese,
            "anno": anno,
            "valori_raw": valori_raw,
            "valori_norm": valori_norm
        }
    except ValueError as e:
        return {"status": "error", "message": str(e)}
    except Exception as e:
        return {"status": "error", "message": f"Errore inatteso: {str(e)}"}
