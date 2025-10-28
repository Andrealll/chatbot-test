from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from openai import OpenAI
import os, time, json
from calcoli import calcola_pianeti_da_df, df_tutti

VERSION = "3.0"
app = FastAPI(title=f"Chatbot Backend DeepSeek v{VERSION}")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 🧠 DeepSeek client (OpenAI-compatible)
client = OpenAI(
    api_key=os.environ.get("DEEPSEEK_API_KEY"),
    base_url="https://api.deepseek.com/v1"
)

@app.get("/")
def home():
    return {"status": "ok", "message": f"DeepSeek backend v{VERSION} attivo"}

@app.post("/run")
async def run(request: Request):
    data = await request.json()
    giorno, mese, anno = int(data["giorno"]), int(data["mese"]), int(data["anno"])

    # Pianeti
    valori_raw, _ = calcola_pianeti_da_df(df_tutti, giorno, mese, anno)
    testo_pianeti = "\n".join([f"{k}: {v:.2f}°" for k,v in valori_raw.items()])

    prompt = f"""
    Data: {giorno}/{mese}/{anno}
    Pianeti:
    {testo_pianeti}

    Genera una breve interpretazione astrologica in italiano, con tono positivo e professionale.
    """

    # DeepSeek model call
    t0 = time.time()
    try:
        resp = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": "Sei un esperto astrologo che scrive con chiarezza e ispirazione."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7,
            max_tokens=400
        )
        testo_gpt = resp.choices[0].message.content
        model_used = resp.model
    except Exception as e:
        testo_gpt = f"Errore DeepSeek: {e}"
        model_used = "none"

    elapsed = int((time.time() - t0) * 1000)

    return {
        "status": "ok",
        "model_used": model_used,
        "giorno": giorno,
        "mese": mese,
        "anno": anno,
        "valori_raw": valori_raw,
        "interpretazione": testo_gpt,
        "response_time_ms": elapsed
    }
