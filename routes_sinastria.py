# routes_sinastria.py
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, Dict, Any
import time

from astrobot_core.sinastria import sinastria as calcola_sinastria
from astrobot_core.calcoli import genera_carta_base64

router = APIRouter(prefix="/sinastria", tags=["sinastria"])


class Persona(BaseModel):
    citta: str
    data: str
    ora: str
    nome: Optional[str] = None


class SinastriaRequest(BaseModel):
    A: Persona
    B: Persona
    scope: str = "sinastria"
    tier: str = "free"


def build_grafico_sinastria_json(result: Dict[str, Any]) -> Dict[str, Any]:
    """
    result: dict restituito da calcola_sinastria,
    dovrebbe contenere:
    - result["A"]["pianeti_decod"]
    - result["B"]["pianeti_decod"]
    """
    serie = []

    tema_A = result.get("A", {})
    tema_B = result.get("B", {})

    pianeti_A = []
    for nome, info in (tema_A.get("pianeti_decod", {}) or {}).items():
        pianeti_A.append({
            "nome": nome,
            "segno": info.get("segno"),
            "gradi_segno": info.get("gradi_segno"),
            "gradi_eclittici": info.get("gradi_eclittici"),
            "retrogrado": info.get("retrogrado", False),
            "theta": info.get("gradi_eclittici"),
            "r": 1.0,
        })
    serie.append({"serie": "A", "pianeti": pianeti_A})

    pianeti_B = []
    for nome, info in (tema_B.get("pianeti_decod", {}) or {}).items():
        pianeti_B.append({
            "nome": nome,
            "segno": info.get("segno"),
            "gradi_segno": info.get("gradi_segno"),
            "gradi_eclittici": info.get("gradi_eclittici"),
            "retrogrado": info.get("retrogrado", False),
            "theta": info.get("gradi_eclittici"),
            "r": 0.8,  # r diverso per distinguerli
        })
    serie.append({"serie": "B", "pianeti": pianeti_B})

    return {
        "tipo": "sinastria_polare",
        "serie": serie,
    }


@router.post("/")
async def sinastria_endpoint(payload: SinastriaRequest):
    start = time.time()
    try:
        result = calcola_sinastria(
            citta_a=payload.A.citta,
            data_a=payload.A.data,
            ora_a=payload.A.ora,
            nome_a=payload.A.nome,
            citta_b=payload.B.citta,
            data_b=payload.B.data,
            ora_b=payload.B.ora,
            nome_b=payload.B.nome,
        )

        sinastria_data = result

        # PNG base64: per ora riuso genera_carta_base64 generico
        png_base64 = genera_carta_base64(
            sinastria_data,
            titolo=f"Sinastria {payload.A.nome or 'A'} - {payload.B.nome or 'B'}",
        )
        if not png_base64.startswith("data:image/png;base64,"):
            png_base64 = "data:image/png;base64," + png_base64

        grafico = build_grafico_sinastria_json(sinastria_data)

        elapsed = time.time() - start

        return {
            "status": "ok",
            "elapsed": elapsed,
            "input": payload.dict(),
            "sinastria": sinastria_data,
            "grafico_polare": grafico,
            "png_base64": png_base64,
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Errore interno /sinastria: {e}")
