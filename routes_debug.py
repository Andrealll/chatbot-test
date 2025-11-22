# routes_debug.py
from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel
import base64

router = APIRouter(prefix="/debug", tags=["Debug"])

class SaveImageBody(BaseModel):
    data_url: str          # tutta la stringa: es. "data:image/png;base64,AAAA..."
    filename: str | None = "grafico.png"

def _parse_data_url(data_url: str):
    if not data_url.startswith("data:"):
        raise ValueError("Stringa non in formato data URL (manca il prefisso 'data:').")
    try:
        header, b64 = data_url.split(",", 1)
    except ValueError:
        raise ValueError("Formato data URL non valido (manca la virgola).")
    if ";base64" not in header:
        raise ValueError("Manca ';base64' nell'intestazione del data URL.")
    mime = header[5:header.index(";base64")] or "application/octet-stream"
    return mime, b64

@router.post("/save-image", summary="Riceve un data:image/png;base64 e restituisce il file scaricabile")
def save_image(body: SaveImageBody):
    try:
        mime, b64 = _parse_data_url(body.data_url.strip())
        raw = base64.b64decode(b64, validate=True)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Data URL non valido: {e}")

    filename = body.filename or "image"
    if "." not in filename and mime == "image/png":
        filename += ".png"

    headers = {
        "Content-Disposition": f'attachment; filename="{filename}"'
    }
    return Response(content=raw, media_type=mime, headers=headers)
