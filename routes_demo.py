# routes_demo.py
import json
from fastapi import APIRouter, Request, Response

from quota import enforce_guest_quota
from demo_image import genera_img_demo_base64

def build_demo_router(supabase_client):
    """
    Costruisce e ritorna un APIRouter /demo con dipendenza su supabase_client.
    Così non creiamo import circolari col main.
    """
    router = APIRouter(prefix="/demo", tags=["demo"])

    @router.post("/transito_oggi")
    async def demo_transito_oggi(request: Request):
        """
        Endpoint LIGHT senza login:
        - Applica rate-limit e quota guest
        - Ritorna testo breve + immagine base64 watermarkata (inline)
        """
        response = Response()
        await enforce_guest_quota(request, response, supabase_client, "demo_transito_oggi")

        # Calcolo LIGHT (placeholder sintetico, pochissime risorse)
        preview_text = (
            "Oggi la Luna forma un aspetto armonico con Venere: "
            "focus su relazioni e benessere. (Versione demo)"
        )
        img_b64 = genera_img_demo_base64(width=512, watermark="AstroBot — demo")

        # Restituiamo manualmente per propagare Set-Cookie (guest_id)
        payload = {"ok": True, "preview": preview_text, "img_base64": img_b64}
        response.media_type = "application/json"
        response.body = json.dumps(payload).encode("utf-8")
        return response

    # (FACOLTATIVO) un secondo endpoint demo:
    @router.post("/tema_anteprima")
    async def demo_tema_anteprima(request: Request):
        response = Response()
        await enforce_guest_quota(request, response, supabase_client, "demo_tema_anteprima")
        preview = [
            "🟣 Sole in Leone — energia, espressione del sé.",
            "🟢 Luna in Sagittario — esplorazione emotiva.",
            "🔵 Ascendente in Vergine — praticità, attenzione al dettaglio."
        ]
        img_b64 = genera_img_demo_base64(width=512, watermark="AstroBot — demo")
        payload = {"ok": True, "bullets": preview, "img_base64": img_b64}
        response.media_type = "application/json"
        response.body = json.dumps(payload).encode("utf-8")
        return response

    return router
