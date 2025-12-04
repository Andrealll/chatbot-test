# routes_tema.py
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, Dict, Any
import time

from astrobot_core.calcoli import genera_carta_base64

router = APIRouter(prefix="/tema", tags=["tema"])


class TemaRequest(BaseModel):
    citta: str
    data: str        # "YYYY-MM-DD"
    ora: str         # "HH:MM"
    nome: Optional[str] = None
    email: Optional[str] = None
    domanda: Optional[str] = None
    scope: str = "tema"
    tier: str = "free"


def build_grafico_tema_json(tema: Dict[str, Any]) -> Dict[str, Any]:
    """
    Costruisce il JSON per il grafico polare a partire dal dict `tema`
    (pianeti_decod, asc_mc_case, case).
    """
    pianeti_decod = tema.get("pianeti_decod", {})
    asc_mc_case = tema.get("asc_mc_case", {})

    pianeti = []
    for nome, info in pianeti_decod.items():
        pianeti.append({
            "nome": nome,
            "segno": info.get("segno"),
            "gradi_segno": info.get("gradi_segno"),
            "gradi_eclittici": info.get("gradi_eclittici"),
            "retrogrado": info.get("retrogrado", False),
            "theta": info.get("gradi_eclittici"),
            "r": 1.0,
        })

    case_raw = asc_mc_case.get("case", []) or []
    case = []
    for idx, start_deg in enumerate(case_raw, start=1):
        case.append({
            "casa": idx,
            "inizio": start_deg,
        })

    grafico = {
        "tipo": "tema_polare",
        "pianeti": pianeti,
        "asc": {
            "angolo": asc_mc_case.get("ASC"),
            "segno": asc_mc_case.get("ASC_segno"),
            "gradi_segno": asc_mc_case.get("ASC_gradi_segno"),
        },
        "mc": {
            "angolo": asc_mc_case.get("MC"),
            "segno": asc_mc_case.get("MC_segno"),
            "gradi_segno": asc_mc_case.get("MC_gradi_segno"),
        },
        "case": case,
    }
    return grafico


def compute_tema_backend(payload: TemaRequest) -> Dict[str, Any]:
    """
    QUI devi copiare la logica che oggi hai nell'endpoint /tema di main.py
    e alla fine restituire un dict `tema` con:
    - pianeti_decod
    - asc_mc_case
    - (eventuale) carta_base64
    - (altri campi che già hai)
    """
    # --- INIZIO: segnaposto da sostituire ---
    raise NotImplementedError("Sposta qui la logica del vecchio /tema di main.py")
    # --- FINE: segnaposto ---
    

@router.post("/")
async def tema_endpoint(payload: TemaRequest):
    start = time.time()
    try:
        # 1) Calcolo del tema (riusa la tua logica esistente)
        tema = compute_tema_backend(payload)

        # 2) PNG base64: se il tema include già 'carta_base64', la riuso
        if "carta_base64" in tema:
            png_base64 = tema["carta_base64"]
        else:
            png_base64 = genera_carta_base64(
                tema,
                titolo=payload.nome or "Tema natale",
            )

        if not png_base64.startswith("data:image/png;base64,"):
            png_base64 = "data:image/png;base64," + png_base64

        # 3) JSON grafico polare
        grafico = build_grafico_tema_json(tema)

        elapsed = time.time() - start

        return {
            "status": "ok",
            "elapsed": elapsed,
            "input": payload.dict(),
            "tema": tema,
            "grafico_polare": grafico,
            "png_base64": png_base64,
        }

    except NotImplementedError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Errore interno /tema: {e}")
