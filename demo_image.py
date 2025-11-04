# demo_image.py
from PIL import Image, ImageDraw
import io, base64, math

def genera_img_demo_base64(width=512, watermark="AstroBot — demo"):
    """
    Genera un'immagine semplice (placeholder) con cerchio zodiacale e watermark.
    Output: data URL base64 pronto da mostrare inline in chat.
    """
    W = width
    H = width
    im = Image.new("RGB", (W, H), (12, 12, 20))
    draw = ImageDraw.Draw(im)

    # cerchio
    r = int(W * 0.42)
    cx, cy = W // 2, H // 2
    draw.ellipse((cx - r, cy - r, cx + r, cy + r), outline=(220, 220, 220), width=2)

    # tacche 12 segni
    for i in range(12):
        ang = (i / 12.0) * 2 * math.pi
        x1 = cx + int((r - 8) * math.cos(ang))
        y1 = cy + int((r - 8) * math.sin(ang))
        x2 = cx + int((r + 8) * math.cos(ang))
        y2 = cy + int((r + 8) * math.sin(ang))
        draw.line((x1, y1, x2, y2), fill=(200, 200, 200), width=2)

    # testo demo
    draw.text((20, 20), "Demo — Transiti Oggi", fill=(240, 240, 240))

    # watermark basso
    wm_y = H - 28
    draw.text((16, wm_y), watermark, fill=(255, 255, 255))

    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=80)
    b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
    return f"data:image/jpeg;base64,{b64}"
