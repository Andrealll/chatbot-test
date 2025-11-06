from fastapi import FastAPI, Request, HTTPException, Body
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime
import time
import os
import uuid

# ================== GESTIONE SESSIONI FREE ==================
# Dizionario in memoria: session_id -> numero di chiamate free
SESSIONS_FREE: Dict[str, int] = {}

# Quante richieste gratuite permettiamo prima del paywall soft
FREE_CALLS_THRESHOLD = 3


def aggiorna_sessione_free(session_id: Optional[str]):
    """
    Gestisce il session_id e il numero di chiamate free.
    Ritorna: (session_id, n_calls_free, paywall_attivo)
    """
    # Se il client non manda un session_id, ne generiamo uno noi
    if not session_id:
        session_id = str(uuid.uuid4())

    # Leggiamo il contatore corrente (default 0) e lo incrementiamo
    n_calls = SESSIONS_FREE.get(session_id, 0) + 1
    SESSIONS_FREE[session_id] = n_calls

    # Paywall attivo se superiamo la soglia
    paywall_attivo = n_calls > FREE_CALLS_THRESHOLD

    return session_id, n_calls, paywall_attivo


# ---- CORE: calcoli & metodi ----
from astrobot_core.calcoli import (
    df_tutti,
    calcola_asc_mc_case,
    calcola_pianeti_da_df,
    decodifica_segni,
    genera_carta_base64,
)
from astrobot_core.metodi import interpreta_groq

# ---- CORE: sinastria & transiti ----
from astrobot_core.sinastria import sinastria as calcola_sinastria

# transiti: import best-effort (alcune funzioni potrebbero non esistere in alcune build)
calcola_transiti_data_fissa = None
transiti_su_due_date = None
transiti_vs_natal_in_data = None
transiti_oggi = None
transiti_su_periodo = None
try:
    from astrobot_core.transiti import calcola_transiti_data_fissa as _ctdf
    calcola_transiti_data_fissa = _ctdf
except Exception:
    pass

try:
    from astrobot_core.transiti import transiti_su_due_date as _tsdd
    transiti_su_due_date = _tsdd
except Exception:
    pass

try:
    from astrobot_core.transiti import tra_
