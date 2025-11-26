@echo off
call conda activate astrobot
cd C:\Users\Utente\Documents\GitHub\chatbot-core\astrobot_core
set BACKEND_URL=http://127.0.0.1:8000
python test_groq_via_backend_payload_ai.py
pause