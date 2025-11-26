
# astrobot_core/plotting.py
from __future__ import annotations
from typing import List, Dict, Any
import io, base64
import matplotlib.pyplot as plt

def moving_average(values: List[float], window: int) -> List[float]:
    if window <= 1 or window > len(values):
        return values[:]
    out = []
    for i in range(len(values)):
        start = max(0, i - window + 1)
        chunk = values[start:i+1]
        out.append(sum(chunk) / len(chunk))
    return out

def trend_bar_png(scores: List[float], labels: List[str], grafica_cfg: Dict[str, Any]) -> str:
    bars_cfg = grafica_cfg.get("bars", {}) if grafica_cfg else {}
    export_cfg = grafica_cfg.get("export", {}) if grafica_cfg else {}
    smoothing = (bars_cfg.get("smoothing", {}) or {})
    baseline_zero = bool(bars_cfg.get("baseline_zero", True))
    title_size = int(bars_cfg.get("title_font_size", 14))
    label_size = int(bars_cfg.get("label_font_size", 10))

    data = scores[:]
    if smoothing.get("enabled", False):
        window = int(smoothing.get("window", 3))
        data = moving_average(data, window)

    fig, ax = plt.subplots(figsize=(export_cfg.get("size_px", {}).get("width", 1200)/100,
                                    export_cfg.get("size_px", {}).get("height", 1200)/100),
                           dpi=export_cfg.get("dpi", 144))

    ax.bar(range(len(data)), data)  # no explicit colors per guidelines
    ax.set_xticks(range(len(labels)))
    ax.set_xticklabels(labels, rotation=45, ha='right', fontsize=label_size)
    ax.set_title("Trend settimanale", fontsize=title_size)
    if baseline_zero:
        ax.set_ylim(bottom=0)

    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight")
    plt.close(fig)
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return "data:image/png;base64," + b64
