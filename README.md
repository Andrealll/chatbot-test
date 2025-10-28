# chatbot-test
# 🪐 AstroBot v3
Un backend FastAPI che calcola Ascendente, Medio Cielo, Case astrologiche e posizioni planetarie (da effemeridi Excel), genera la carta polare e produce un’interpretazione AI con Groq.

---

## 🚀 Funzionalità
- Calcolo **Ascendente**, **Medio Cielo**, **Case astrologiche**
- Lettura di **pianeti e punti sensibili** da `effemeridi_1950_2025.xlsx`
- Generazione della **carta polare astrologica** (Matplotlib)
- **Interpretazione automatica** tramite modello AI Groq (`llama-3.3-70b-versatile`)
- Endpoint API REST JSON e immagine Base64

---

## 📦 Requisiti
- Python 3.11 o superiore
- File `effemeridi_1950_2025.xlsx` nella root del progetto
- Chiave API Groq attiva ([https://console.groq.com/keys](https://console.groq.com/keys))

---

## 📁 Struttura progetto


astrobot/
│
├── main.py
├── calcoli.py
├── requirements.txt
├── effemeridi_1950_2025.xlsx
└── README.md


---

## ⚙️ Installazione locale

### 1️⃣ Crea un ambiente virtuale
```bash
python -m venv .venv
source .venv/bin/activate   # su Windows: .venv\Scripts\activate

2️⃣ Installa le dipendenze
pip install -r requirements.txt

3️⃣ Avvia il server
uvicorn main:app --host 0.0.0.0 --port 10000


Server attivo su:
👉 http://127.0.0.1:10000

🌐 Deploy su Render

Vai su https://render.com

Clicca “New +” → Web Service

Connetti il tuo repo GitHub

Imposta:

Build Command:

pip install -r requirements.txt


Start Command:

uvicorn main:app --host 0.0.0.0 --port 10000


Environment: Python 3.11

Plan: Free (sufficiente per test)

Aggiungi variabile ambiente:

GROQ_API_KEY = la_tua_chiave


Clicca Deploy Web Service

Render costruirà e pubblicherà automaticamente il servizio.
Vedrai nei log:

==> Build successful 🎉
==> Your service is live 🎉
==> Available at https://astrobot-xxxxx.onrender.com

🔍 Test API
🔸 Stato server
GET / → https://astrobot-xxxxx.onrender.com/


Risposta:

{"status":"ok","message":"AstroBot v3 online 🪐"}

🔸 Tema natale completo
GET /tema?citta=Napoli&giorno=19&mese=7&anno=1986&ora=8&minuti=50


Risposta:

{
  "status": "ok",
  "ascendente": {
    "ASC_segno": "♍ Vergine",
    "MC_segno": "♏ Scorpione",
    ...
  },
  "pianeti": {"Sole": 116.04, "Luna": 261.79, ...},
  "interpretazione": "Hai un ascendente in Vergine...",
  "image_base64": "iVBORw0KGgoAAAANSUhEUgAA...",
  "elapsed_ms": 623
}

🔸 Visualizzare la carta

In un frontend (o bot):

<img src="data:image/png;base64,{{response.image_base64}}" alt="Carta natale"/>

🧠 Modelli AI supportati

Attualmente viene usato:

Groq API → modello llama-3.3-70b-versatile

Temperatura: 0.6

Max token: 600

Puoi modificare in calcoli.py per usare un tuo modello.

🪶 Credits

Andrea Lombardi — Data Science, Coaching e AI Design

Librerie: FastAPI, Skyfield, Matplotlib, Pandas, Groq API

Carta polare ispirata al progetto “Cambio-mente 🌱”

🧭 Licenza

MIT License © 2025 Andrea Lombardi


---

👉 **Ora basta:**
1️⃣ aggiungi questo file nel repo,  
2️⃣ fai `git push`,  
3️⃣ Render lo riconoscerà e rifarà il deploy automatico.  
