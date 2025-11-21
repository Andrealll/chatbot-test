import base64
from pathlib import Path

# Legge la stringa dal file
data = Path("grafico.txt").read_text(encoding="utf-8").strip()

# Rimuove il prefisso se presente
prefix = "data:image/png;base64,"
if data.startswith(prefix):
    data = data[len(prefix):]

# Decodifica e salva
img_bytes = base64.b64decode(data)
Path("grafico.png").write_bytes(img_bytes)
print(f"OK: salvato grafico.png ({len(img_bytes)} bytes)")
