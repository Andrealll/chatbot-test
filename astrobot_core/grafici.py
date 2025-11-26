"""
Modulo grafici per AstroBot.

Contiene funzioni pure che generano grafici (matplotlib) e restituiscono
stringhe base64 (PNG) senza prefisso "data:image/png;base64,".

- grafico_linee_premium: serie storica 5 dimensioni (transiti)
- grafico_tema_natal / genera_carta_tema: tema natale
- grafico_sinastria / genera_carta_sinastria: sinastria
"""

from __future__ import annotations

import base64
import io
from datetime import datetime
from math import isfinite
from typing import Dict, List, Optional, Tuple

import matplotlib
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.gridspec import GridSpec

# backend non interattivo per ambienti server/headless
matplotlib.use("Agg")


# ---------------------------------------------------------------------------
# Costanti di stile comuni
# ---------------------------------------------------------------------------

# Segni zodiacali (ordine Ariete -> Pesci)
ZODIAC_GLYPHS: List[str] = [
    "♈", "♉", "♊", "♋",  # Ariete, Toro, Gemelli, Cancro
    "♌", "♍", "♎", "♏",  # Leone, Vergine, Bilancia, Scorpione
    "♐", "♑", "♒", "♓",  # Sagittario, Capricorno, Acquario, Pesci
]

# Glifi planetari (tema + sinastria)
PLANET_GLYPHS: Dict[str, str] = {
    "Sole": "☉",
    "Luna": "☽",
    "Mercurio": "☿",
    "Venere": "♀",
    "Marte": "♂",
    "Giove": "♃",
    "Saturno": "♄",
    "Urano": "♅",
    "Nettuno": "♆",
    "Plutone": "♇",
    # nodi / punti
    "Nodo": "☊",
    "Nodo Nord": "☊",
    "Nodo Sud": "☋",
    "Lilith": "⚸",
}

# Ordine classico per le liste di pianeti in sinastria
SINASTRIA_PLANET_ORDER: List[str] = [
    "Sole", "Luna", "Mercurio", "Venere", "Marte",
    "Giove", "Saturno", "Urano", "Nettuno", "Plutone",
    "Nodo", "Lilith",
]

# Colori standard per i 5 domini dei transiti
DEFAULT_COLORS: Dict[str, str] = {
    "energy": "#6C5DD3",        # viola
    "emotions": "#4ECDC4",      # turchese
    "relationships": "#EF476F", # rosa/rosso
    "work": "#3B82F6",          # blu
    "luck": "#F6C453",          # oro
}

# Etichette di default (italiano) per i 5 domini
DEFAULT_LABEL_MAP_IT: Dict[str, str] = {
    "energy": "Energia",
    "emotions": "Emozioni",
    "relationships": "Relazioni",
    "work": "Lavoro",
    "luck": "Fortuna",
}


# ---------------------------------------------------------------------------
# Helper generico
# ---------------------------------------------------------------------------

def _fig_to_base64(fig) -> str:
    """
    Converte una figura matplotlib in PNG base64 (senza prefisso data URI).

    - sfondo bianco (no trasparente)
    - assi con facecolor bianco
    """
    # Sfondo bianco per la figura
    fig.patch.set_facecolor("white")

    # Sfondo bianco per tutti gli assi
    for ax in fig.axes:
        ax.set_facecolor("white")

    buf = io.BytesIO()
    fig.savefig(
        buf,
        format="png",
        bbox_inches="tight",
        facecolor="white",  # niente transparent=True
    )
    plt.close(fig)
    buf.seek(0)
    return base64.b64encode(buf.getvalue()).decode("utf-8")


# ---------------------------------------------------------------------------
# 1) Grafico a linee premium – 5 dimensioni, versione "light"
# ---------------------------------------------------------------------------

def grafico_linee_premium(
    date_strings: List[str],
    intensities_series: Dict[str, List[float]],
    scope: str,
    label_map: Optional[Dict[str, str]] = None,
) -> str:
    """
    Grafico a linee premium (serie storica, 5 dimensioni).

    - niente titolo
    - niente label asse Y
    - niente watermark

    L'unico testo sono i nomi delle linee, presi da `label_map`, usati:
    - nella legenda in basso
    - nei callout a destra
    """
    # Ordine fisso dei domini
    domain_order = ["energy", "emotions", "relationships", "work", "luck"]

    # Label di default (italiano)
    if label_map is None:
        label_map_effective = DEFAULT_LABEL_MAP_IT
    else:
        label_map_effective = DEFAULT_LABEL_MAP_IT.copy()
        label_map_effective.update(label_map)

    # Conversione date stringa -> datetime
    dates = [datetime.strptime(d, "%Y-%m-%d") for d in date_strings]
    dates_mpl = mdates.date2num(dates)

    # Controllo consistenza
    n_points = len(dates)
    if n_points == 0:
        raise ValueError("grafico_linee_premium: nessuna data fornita.")

    for k, serie in intensities_series.items():
        if len(serie) != n_points:
            raise ValueError(
                f"grafico_linee_premium: lunghezza serie per '{k}' "
                f"({len(serie)}) diversa da numero date ({n_points})."
            )

    fig, ax = plt.subplots(figsize=(7, 4), dpi=150)

    line_endpoints: Dict[str, float] = {}
    handles = []
    labels_for_legend: List[str] = []

    # Palette linee
    for domain in domain_order:
        if domain not in intensities_series:
            continue

        values = [float(v) for v in intensities_series[domain]]
        values = [v if isfinite(v) else 0.0 for v in values]

        label = label_map_effective.get(domain, domain.capitalize())
        color = DEFAULT_COLORS.get(domain, None)

        (line_handle,) = ax.plot(
            dates_mpl,
            values,
            marker="o",
            linewidth=1.8,
            markersize=4,
            label=label,
            color=color,
        )

        line_endpoints[domain] = values[-1]
        handles.append(line_handle)
        labels_for_legend.append(label)

    if not line_endpoints:
        raise ValueError("grafico_linee_premium: nessuna serie valida da plottare.")

    # Asse X: date gg/mm (neutro rispetto lingua)
    locator = mdates.AutoDateLocator()
    formatter = mdates.DateFormatter("%d/%m")
    ax.xaxis.set_major_locator(locator)
    ax.xaxis.set_major_formatter(formatter)
    plt.setp(ax.get_xticklabels(), rotation=45, ha="right", fontsize=8)

    # Asse Y in percentuale 0–100%
    ax.set_ylim(0, 1.05)
    yticks = np.linspace(0.0, 1.0, 6)
    ax.set_yticks(yticks)
    ax.set_yticklabels([f"{int(y * 100)}%" for y in yticks], fontsize=8)

    # Griglia orizzontale leggera
    ax.yaxis.grid(True, linestyle=":", alpha=0.4)
    ax.set_axisbelow(True)

    # Legenda in basso
    if handles:
        ax.legend(
            handles,
            labels_for_legend,
            loc="upper center",
            bbox_to_anchor=(0.5, -0.18),
            ncol=3,
            fontsize=7,
            frameon=False,
        )

    # Pulizia bordi
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    # Callout a destra
    x_min = min(dates_mpl)
    x_max = max(dates_mpl)
    x_offset = (x_max - x_min) * 0.18 if x_max > x_min else 1.0
    x_text = x_max + x_offset

    ordered_domains = sorted(
        [d for d in domain_order if d in line_endpoints],
        key=lambda d: line_endpoints[d],
    )

    min_delta_y = 0.05
    prev_y_label = None
    x_last = x_max

    for domain in ordered_domains:
        y_point = line_endpoints[domain]
        label = label_map_effective.get(domain, domain.capitalize())

        y_label_pos = y_point
        if prev_y_label is not None and abs(y_label_pos - prev_y_label) < min_delta_y:
            y_label_pos = prev_y_label + min_delta_y

        ax.annotate(
            label,
            xy=(x_last, y_point),
            xytext=(x_text, y_label_pos),
            textcoords="data",
            ha="left",
            va="center",
            fontsize=8,
            arrowprops=dict(
                arrowstyle="-",
                linewidth=0.8,
                alpha=0.7,
            ),
        )

        prev_y_label = y_label_pos

    ax.set_xlim(x_min, x_max)

    fig.tight_layout()
    return _fig_to_base64(fig)


# ---------------------------------------------------------------------------
# 2) Tema natale (con balloon gialli + spessore stile sinastria)
# ---------------------------------------------------------------------------

def _scatter_planets_with_conjunctions(
    ax,
    longitudes: Dict[str, float],
    r_base: float,
    marker: str,
    s: float,
    color: str,
    tol_deg: float = 2.0,
):
    """
    Disegna i pianeti su un anello a r_base gestendo le congiunzioni.
    """
    if not longitudes:
        return

    items = list(longitudes.items())
    thetas = {name: np.deg2rad(float(deg) % 360.0) for name, deg in items}

    # cluster di pianeti vicini
    clusters: List[List[int]] = []
    used: set[int] = set()
    tol = np.deg2rad(tol_deg)

    for i in range(len(items)):
        if i in used:
            continue
        cluster = [i]
        used.add(i)
        for j in range(i + 1, len(items)):
            if j in used:
                continue
            d = abs(thetas[items[i][0]] - thetas[items[j][0]])
            d = min(d, 2 * np.pi - d)
            if d <= tol:
                cluster.append(j)
                used.add(j)
        clusters.append(cluster)

    # disegno cluster
    for cluster in clusters:
        n = len(cluster)
        theta_cluster = float(
            np.mean([thetas[items[i][0]] for i in cluster])
        )

        if n == 1:
            # caso singolo pianeta
            idx = cluster[0]
            name, _ = items[idx]
            theta = thetas[name]
            glyph = PLANET_GLYPHS.get(name, name[0])

            ax.text(
                theta,
                r_base,
                glyph,
                ha="center",
                va="center",
                fontsize=20,
                color=color,
                zorder=4,
            )
        else:
            # cluster 2+ pianeti → puntino + callout
            ax.scatter(
                [theta_cluster],
                [r_base],
                s=s * 0.7,
                facecolor="black",
                edgecolor="none",
                zorder=4,
            )

            label = "".join(
                PLANET_GLYPHS.get(items[i][0], items[i][0][0]) for i in cluster
            )
            ax.annotate(
                label,
                xy=(theta_cluster, r_base),
                xytext=(theta_cluster, r_base + 0.08),
                ha="center",
                va="bottom",
                fontsize=13,
                arrowprops=dict(
                    arrowstyle="-",
                    linewidth=0.8,
                ),
                zorder=5,
            )


def _assegna_casa(longitudine: float, case_longitudini: List[float]) -> Optional[int]:
    """
    Ritorna il numero di casa (1..12) dato pianeta + cuspidi.
    """
    if not case_longitudini or len(case_longitudini) != 12:
        return None

    lon = float(longitudine) % 360.0
    cusps = [c % 360.0 for c in case_longitudini]

    for i in range(12):
        start = cusps[i]
        end = cusps[(i + 1) % 12]
        span = (end - start) % 360.0
        rel = (lon - start) % 360.0
        if rel < span:
            return i + 1

    return None


def _build_planet_legend_rows(
    pianeti_decod: Dict[str, Dict[str, float]],
    asc_mc_case: Dict[str, object],
) -> List[Dict[str, object]]:
    """
    Righe per la legenda laterale del tema natale:
    simbolo pianeta, gradi nel segno, simbolo segno, casa.
    """
    case_long = asc_mc_case.get("case") if asc_mc_case else None
    rows: List[Dict[str, object]] = []

    for name, data in pianeti_decod.items():
        lon = float(data["gradi_eclittici"]) % 360.0

        sign_index = int(lon // 30) % 12
        segno_glyph = ZODIAC_GLYPHS[sign_index]
        deg_segno = lon % 30.0
        casa = _assegna_casa(lon, case_long) if case_long else None
        glyph = PLANET_GLYPHS.get(name, name[0])

        rows.append(
            {
                "name": name,
                "glyph": glyph,
                "lon": lon,
                "deg_segno": deg_segno,
                "segno_glyph": segno_glyph,
                "casa": casa,
            }
        )

    return rows


def _build_aspect_legend_rows(aspetti: Optional[List[Dict[str, object]]]) -> List[Dict[str, object]]:
    """
    Righe per la legenda degli aspetti del tema (max 12, ordinate per orb).
    """
    if not aspetti:
        return []

    aspect_glyphs = {
        "congiunzione": "☌",
        "trigono": "△",
        "sestile": "✶",
        "quadratura": "□",
        "opposizione": "☍",
    }

    aspetti_sorted = sorted(
        aspetti,
        key=lambda a: float(a.get("orb", a.get("delta", 99.0))),
    )

    rows: List[Dict[str, object]] = []
    for asp in aspetti_sorted[:12]:
        p1 = asp.get("pianeta1")
        p2 = asp.get("pianeta2")
        if not p1 or not p2:
            continue

        tipo = (asp.get("tipo") or "").lower()
        orb = float(asp.get("orb", asp.get("delta", 0.0)))

        g1 = PLANET_GLYPHS.get(p1, p1[0])
        g2 = PLANET_GLYPHS.get(p2, p2[0])
        g_aspetto = aspect_glyphs.get(tipo, tipo[:3])

        rows.append(
            {
                "g1": g1,
                "g_aspetto": g_aspetto,
                "g2": g2,
                "orb": orb,
                "tipo": tipo,
            }
        )

    return rows


def _disegna_aspetti_tema(
    ax,
    pianeti_long: Dict[str, float],
    aspetti: Optional[List[Dict[str, object]]],
    r_aspetti: float = 0.70,
):
    """
    Aspetti tema natale con:
    - colori armonici/difficili
    - spessore linea inverso all'orb (stessa formula sinastria)
    - balloon giallo sulle congiunzioni.
    """
    if not aspetti:
        return

    armonici = {"trigono", "sestile"}
    difficili = {"quadratura", "opposizione"}

    for asp in aspetti:
        p1 = asp.get("pianeta1")
        p2 = asp.get("pianeta2")
        if p1 not in pianeti_long or p2 not in pianeti_long:
            continue

        deg1 = float(pianeti_long[p1]) % 360.0
        deg2 = float(pianeti_long[p2]) % 360.0
        th1 = np.deg2rad(deg1)
        th2 = np.deg2rad(deg2)

        tipo = (asp.get("tipo") or "").lower()
        orb = float(asp.get("orb", asp.get("delta", 5.0)))

        # colori
        if tipo in armonici:
            color = "tab:blue"
        elif tipo in difficili:
            color = "tab:red"
        else:
            color = "gray"

        # spessore inversamente proporzionale all'orb (sincronizzato a sinastria)
        orb_clamped = min(max(orb, 0.1), 2.0)
        strength = 1.0 - orb_clamped / 2.0
        lw_min, lw_max = 0.1, 3.5
        lw = lw_min + strength * (lw_max - lw_min)

        # linea tra i due pianeti, sulla stessa corona r_aspetti
        ax.plot(
            [th1, th2],
            [r_aspetti, r_aspetti],
            color=color,
            lw=lw,
            alpha=0.9,
            zorder=2,
        )

        # balloon giallo se congiunzione
        if tipo == "congiunzione":
            theta_mid = (th1 + th2) / 2.0
            ax.scatter(
                [theta_mid],
                [r_aspetti],
                s=150,
                facecolor="yellow",
                edgecolor="none",
                alpha=0.4,
                zorder=3,
            )


def grafico_tema_natal(
    pianeti_decod: Dict[str, Dict[str, object]],
    asc_mc_case: Optional[Dict[str, object]] = None,
    aspetti: Optional[List[Dict[str, object]]] = None,
    figsize: Tuple[float, float] = (14, 7),
) -> str:
    """
    Genera la carta del Tema Natale (ruota + legende) e restituisce
    una stringa PNG base64 (senza prefisso data URI).
    """
    # Preparazione dati
    pianeti_natal = {k: v["gradi_eclittici"] for k, v in pianeti_decod.items()}
    legend_rows = _build_planet_legend_rows(pianeti_decod, asc_mc_case or {})
    aspect_rows = _build_aspect_legend_rows(aspetti)

    # Figura: polar + 2 legende
    fig = plt.figure(figsize=figsize, dpi=150)
    gs = GridSpec(1, 3, width_ratios=[1.7, 1.1, 1.1], wspace=0.35)

    ax = fig.add_subplot(gs[0, 0], projection="polar")  # ruota
    ax_leg_plan = fig.add_subplot(gs[0, 1])             # legenda pianeti
    ax_leg_aspe = fig.add_subplot(gs[0, 2])             # legenda aspetti

    for axx in (ax_leg_plan, ax_leg_aspe):
        axx.axis("off")

    ax.set_theta_zero_location("N")
    ax.set_theta_direction(-1)

    # niente tick radiali / numeri 0.2, 0.4, ...
    ax.set_yticks([])
    ax.set_yticklabels([])

    r_ruota = 1.0
    r_segni_outer = 1.25
    ax.set_ylim(0, 1.35)
    ax.grid(False)

    # Cerchi + anello dei segni
    theta_circ = np.linspace(0, 2 * np.pi, 720)
    ax.plot(theta_circ, [r_ruota] * len(theta_circ), color="black", lw=1.0)
    ax.plot(theta_circ, [r_segni_outer] * len(theta_circ), color="black", lw=1.0)

    for deg in range(0, 360, 30):
        theta = np.deg2rad(deg)
        ax.plot([theta, theta], [r_ruota, r_segni_outer], color="black", lw=0.8)

    r_segni_mid = (r_ruota + r_segni_outer) / 2.0
    for i, glyph in enumerate(ZODIAC_GLYPHS):
        deg_center = i * 30 + 15
        theta = np.deg2rad(deg_center)
        ax.text(theta, r_segni_mid, glyph, ha="center", va="center", fontsize=16)

    # Aspetti (con balloon + spessore sinastria)
    _disegna_aspetti_tema(ax, pianeti_natal, aspetti, r_aspetti=0.70)

    # ASC, MC, DS, IC
    if asc_mc_case:
        segni_ordine = [
            "Ariete", "Toro", "Gemelli", "Cancro", "Leone", "Vergine",
            "Bilancia", "Scorpione", "Sagittario", "Capricorno", "Acquario", "Pesci",
        ]
        base_segno = {nome: i * 30 for i, nome in enumerate(segni_ordine)}

        asc_deg = base_segno[asc_mc_case["ASC_segno"]] + asc_mc_case["ASC_gradi_segno"]
        asc_theta = np.deg2rad(asc_deg)
        ax.plot([asc_theta, asc_theta], [0, r_ruota], color="black", lw=2.4)
        ax.text(
            asc_theta,
            r_ruota * 1.03,
            "ASC",
            ha="center",
            va="bottom",
            fontsize=11,
            fontweight="bold",
        )

        mc_deg = base_segno[asc_mc_case["MC_segno"]] + asc_mc_case["MC_gradi_segno"]
        mc_theta = np.deg2rad(mc_deg)
        ax.plot([mc_theta, mc_theta], [0, r_ruota], color="black", lw=2.4)
        ax.text(
            mc_theta,
            r_ruota * 1.03,
            "MC",
            ha="center",
            va="bottom",
            fontsize=11,
            fontweight="bold",
        )

        # DS opposto all'ASC, IC opposto al MC
        ds_theta = asc_theta + np.pi
        ic_theta = mc_theta + np.pi

        ax.plot([ds_theta, ds_theta], [0, r_ruota], color="black", lw=1.4, linestyle="--")
        ax.text(
            ds_theta,
            r_ruota * 1.03,
            "DS",
            ha="center",
            va="bottom",
            fontsize=10,
        )

        ax.plot([ic_theta, ic_theta], [0, r_ruota], color="black", lw=1.4, linestyle="--")
        ax.text(
            ic_theta,
            r_ruota * 1.03,
            "IC",
            ha="center",
            va="bottom",
            fontsize=10,
        )

    # Pianeti natali (ORA NERI)
    _scatter_planets_with_conjunctions(
        ax,
        pianeti_natal,
        r_base=0.78,
        marker="o",
        s=70,
        color="black",   # prima era "white"
    )

    # LEGENDA PIANETI
    ax_leg_plan.text(
        0.0,
        0.98,
        "Pianeti",
        fontsize=11,
        fontweight="bold",
        transform=ax_leg_plan.transAxes,
    )

    y0 = 0.90
    dy = 0.07

    for i, row in enumerate(legend_rows):
        y = y0 - i * dy

        casa_str = f" Casa {row['casa']}" if row["casa"] is not None else ""

        x_glyph_planet = -0.15
        x_text_deg = 0.0
        x_glyph_sign = 0.20
        x_text_casa = 0.28

        ax_leg_plan.text(
            x_glyph_planet,
            y,
            row["glyph"],
            fontsize=18,
            transform=ax_leg_plan.transAxes,
            va="center",
        )

        ax_leg_plan.text(
            x_text_deg,
            y,
            f"{row['deg_segno']:.1f}°",
            fontsize=10,
            transform=ax_leg_plan.transAxes,
            va="center",
        )

        ax_leg_plan.text(
            x_glyph_sign,
            y,
            row["segno_glyph"],
            fontsize=13,
            transform=ax_leg_plan.transAxes,
            va="center",
        )

        ax_leg_plan.text(
            x_text_casa,
            y,
            casa_str,
            fontsize=10,
            transform=ax_leg_plan.transAxes,
            va="center",
        )

    # LEGENDA ASPETTI
    ax_leg_aspe.text(
        0.0,
        0.98,
        "Aspetti",
        fontsize=11,
        fontweight="bold",
        transform=ax_leg_aspe.transAxes,
    )

    if aspect_rows:
        y0 = 0.90
        dy = 0.07
        for i, row in enumerate(aspect_rows):
            y = y0 - i * dy
            txt = f"{row['g1']} {row['g_aspetto']} {row['g2']}  {row['orb']:.1f}°"
            ax_leg_aspe.text(
                0.0,
                y,
                txt,
                fontsize=10,
                transform=ax_leg_aspe.transAxes,
                va="center",
            )

    fig.tight_layout()
    return _fig_to_base64(fig)


# Alias per compatibilità con il notebook originale
def genera_carta_tema(
    pianeti_decod,
    asc_mc_case=None,
    aspetti=None,
    figsize=(14, 7),
) -> str:
    return grafico_tema_natal(pianeti_decod, asc_mc_case, aspetti, figsize)


# ---------------------------------------------------------------------------
# 3) Sinastria
# ---------------------------------------------------------------------------

def _scatter_planets_sinastria(
    ax,
    longitudes_A: Dict[str, float],
    longitudes_B: Dict[str, float],
    r_A: float = 0.78,
    r_B: float = 1.02,
):
    """
    Disegna i pianeti di A e B su due anelli:
    - A sull'anello interno (r_A)
    - B sull'anello esterno (r_B)
    """
    # Persona A (nero)
    for name, deg in longitudes_A.items():
        theta = np.deg2rad(float(deg) % 360.0)
        glyph = PLANET_GLYPHS.get(name, name[0])
        ax.text(
            theta,
            r_A,
            glyph,
            ha="center",
            va="center",
            fontsize=16,
            color="black",
            zorder=4,
        )

    # Persona B (grigio)
    for name, deg in longitudes_B.items():
        theta = np.deg2rad(float(deg) % 360.0)
        glyph = PLANET_GLYPHS.get(name, name[0])
        ax.text(
            theta,
            r_B,
            glyph,
            ha="center",
            va="center",
            fontsize=16,
            color="gray",
            zorder=4,
        )


def _disegna_aspetti_sinastria(
    ax,
    pianeti_A_long: Dict[str, float],
    pianeti_B_long: Dict[str, float],
    aspetti_AB: List[Dict[str, object]],
    r_A: float = 0.78,
    r_B: float = 1.02,
    r_sep: Optional[float] = None,
):
    """
    Linee A–B con spessore in funzione dell'orb
    + balloon gialli sulle congiunzioni.
    """
    if not aspetti_AB:
        return

    if r_sep is None:
        r_sep = (r_A + r_B) / 2.0

    armonici = {"trigono", "sestile"}
    difficili = {"quadratura", "opposizione"}

    for asp in aspetti_AB:
        pa = asp.get("pianetaA")
        pb = asp.get("pianetaB")
        if pa not in pianeti_A_long or pb not in pianeti_B_long:
            continue

        degA = float(pianeti_A_long[pa]) % 360.0
        degB = float(pianeti_B_long[pb]) % 360.0
        thA = np.deg2rad(degA)
        thB = np.deg2rad(degB)

        tipo = (asp.get("tipo") or "").lower()
        orb = float(asp.get("orb", asp.get("delta", 5.0)))

        # colori
        if tipo in armonici:
            color = "tab:blue"
        elif tipo in difficili:
            color = "tab:red"
        else:
            color = "gray"

        # spessore inversamente proporzionale all'orb
        orb_clamped = min(max(orb, 0.1), 2.0)
        strength = 1.0 - orb_clamped / 2.0
        lw_min, lw_max = 0.1, 3.5
        lw = lw_min + strength * (lw_max - lw_min)

        # linea A–B
        ax.plot(
            [thA, thB],
            [r_A, r_B],
            color=color,
            lw=lw,
            alpha=0.9,
            zorder=2,
        )

        # balloon giallo sulle congiunzioni
        if tipo == "congiunzione":
            theta_mid = (thA + thB) / 2.0
            ax.scatter(
                [theta_mid],
                [r_sep],
                s=150,
                facecolor="yellow",
                edgecolor="none",
                alpha=0.4,
                zorder=3,
            )


def _build_sinastria_legend_rows(
    pianeti_A_decod: Dict[str, Dict[str, object]],
    pianeti_B_decod: Dict[str, Dict[str, object]],
) -> List[Dict[str, object]]:
    """
    Righe per tabella sinastria:
    - prima colonna: simbolo pianeta (ordine astrologico)
    - A: gradi+segno persona A
    - B: gradi+segno persona B
    """
    rows: List[Dict[str, object]] = []

    union = set(pianeti_A_decod.keys()) | set(pianeti_B_decod.keys())

    all_names = [
        name for name in SINASTRIA_PLANET_ORDER if name in union
    ] + [
        name for name in sorted(union) if name not in SINASTRIA_PLANET_ORDER
    ]

    for name in all_names:
        dataA = pianeti_A_decod.get(name)
        dataB = pianeti_B_decod.get(name)

        def _fmt(data: Optional[Dict[str, object]]) -> str:
            if not data:
                return "-"
            lon = float(data["gradi_eclittici"]) % 360.0
            sign_index = int(lon // 30) % 12
            deg_segno = lon % 30.0
            segno = ZODIAC_GLYPHS[sign_index]
            return f"{deg_segno:.1f}° {segno}"

        rows.append(
            {
                "name": name,
                "glyph": PLANET_GLYPHS.get(name, name[0]),
                "A": _fmt(dataA),
                "B": _fmt(dataB),
            }
        )

    return rows


def _build_sinastria_aspect_lists(
    aspetti_AB: Optional[List[Dict[str, object]]],
) -> Tuple[List[Dict[str, object]], List[Dict[str, object]]]:
    """
    Lista aspetti positivi (trigono, sestile) e difficili (quadratura, opposizione),
    ordinati per orb, max 5 per gruppo.
    """
    if not aspetti_AB:
        return [], []

    aspect_glyphs = {
        "congiunzione": "☌",
        "trigono": "△",
        "sestile": "✶",
        "quadratura": "□",
        "opposizione": "☍",
    }
    armonici = {"trigono", "sestile"}
    difficili = {"quadratura", "opposizione"}

    positivi: List[Dict[str, object]] = []
    negativi: List[Dict[str, object]] = []

    for asp in aspetti_AB:
        pA = asp.get("pianetaA")
        pB = asp.get("pianetaB")
        if not pA or not pB:
            continue

        tipo_raw = asp.get("tipo") or ""
        tipo = tipo_raw.lower().strip()
        orb = float(asp.get("orb", asp.get("delta", 99.0)))

        gA = PLANET_GLYPHS.get(pA, pA[0])
        gB = PLANET_GLYPHS.get(pB, pB[0])
        g_asp = aspect_glyphs.get(tipo, tipo[:3])

        row = {
            "glyphA": gA,
            "glyphAsp": g_asp,
            "glyphB": gB,
            "orb": orb,
            "tipo": tipo_raw,
        }

        if tipo in armonici:
            positivi.append(row)
        elif tipo in difficili:
            negativi.append(row)
        else:
            # congiunzioni o altri tipi neutri → ignorati qui
            pass

    positivi = sorted(positivi, key=lambda r: r["orb"])[:5]
    negativi = sorted(negativi, key=lambda r: r["orb"])[:5]

    return positivi, negativi


def grafico_sinastria(
    pianeti_A_decod: Dict[str, Dict[str, object]],
    pianeti_B_decod: Dict[str, Dict[str, object]],
    aspetti_AB: Optional[List[Dict[str, object]]] = None,
    nome_A: str = "A",
    nome_B: str = "B",
    figsize: Tuple[float, float] = (12, 7),
) -> str:
    """
    Grafico sinastria completo (ruota + pannello destro).
    """
    pianeti_A_long = {k: v["gradi_eclittici"] for k, v in pianeti_A_decod.items()}
    pianeti_B_long = {k: v["gradi_eclittici"] for k, v in pianeti_B_decod.items()}

    legend_rows = _build_sinastria_legend_rows(pianeti_A_decod, pianeti_B_decod)
    aspetti_pos, aspetti_neg = _build_sinastria_aspect_lists(aspetti_AB or [])

    fig = plt.figure(figsize=figsize, dpi=150)
    gs = GridSpec(1, 2, width_ratios=[1.6, 1.4], wspace=0.30)

    ax = fig.add_subplot(gs[0, 0], projection="polar")  # ruota sinastria
    ax_leg = fig.add_subplot(gs[0, 1])                  # pannello legende
    ax_leg.axis("off")

    ax.set_theta_zero_location("N")
    ax.set_theta_direction(-1)

    # niente tick radiali / numeri 0.2, 0.4, ...
    ax.set_yticks([])
    ax.set_yticklabels([])

    # raggi principali
    r_A = 0.70
    r_sep = 0.86
    r_B = 1.02
    r_ruota = 1.08
    r_segni_outer = 1.25

    ax.set_ylim(0, 1.35)
    ax.grid(False)

    # Cerchi + anello segni
    theta_circ = np.linspace(0, 2 * np.pi, 720)
    ax.plot(theta_circ, [r_ruota] * len(theta_circ), color="black", lw=1.0)
    ax.plot(theta_circ, [r_sep] * len(theta_circ), color="black", lw=0.8, linestyle=":")
    ax.plot(theta_circ, [r_segni_outer] * len(theta_circ), color="black", lw=1.0)

    for deg in range(0, 360, 30):
        theta = np.deg2rad(deg)
        ax.plot([theta, theta], [r_ruota, r_segni_outer], color="black", lw=0.8)

    r_segni_mid = (r_ruota + r_segni_outer) / 2.0
    for i, glyph in enumerate(ZODIAC_GLYPHS):
        deg_center = i * 30 + 15
        theta = np.deg2rad(deg_center)
        ax.text(theta, r_segni_mid, glyph, ha="center", va="center", fontsize=16)

    # Aspetti + balloon congiunzioni
    _disegna_aspetti_sinastria(
        ax,
        pianeti_A_long,
        pianeti_B_long,
        aspetti_AB or [],
        r_A=r_A,
        r_B=r_B,
        r_sep=r_sep,
    )

    # Pianeti A e B
    _scatter_planets_sinastria(
        ax,
        pianeti_A_long,
        pianeti_B_long,
        r_A=r_A,
        r_B=r_B,
    )

    # Titolo
    ax.set_title(
        f"Sinastria {nome_A} – {nome_B}",
        fontsize=12,
        fontweight="bold",
        pad=12,
    )

    # PANNELLO DESTRO: pianeti + aspetti
    ax_leg.text(
        0.0,
        0.96,
        f"{nome_A} vs {nome_B}",
        fontsize=11,
        fontweight="bold",
        transform=ax_leg.transAxes,
        va="center",
        ha="left",
    )

    y = 0.90
    dy = 0.05

    for row in legend_rows:
        txt = f"{row['glyph']}  {row['A']}   |   {row['B']}"
        ax_leg.text(
            0.0,
            y,
            txt,
            fontsize=9,
            transform=ax_leg.transAxes,
            va="center",
            ha="left",
        )
        y -= dy

    # spazio
    y -= 0.04

    # Aspetti positivi
    if aspetti_pos:
        x_text = 0.0
        ax_leg.text(
            x_text,
            y,
            "Aspetti positivi / Positive aspects",
            fontsize=9,
            fontweight="bold",
            transform=ax_leg.transAxes,
            va="center",
            ha="left",
        )
        y -= 0.04

        for row in aspetti_pos:
            txt = f"{row['glyphA']} {row['glyphAsp']} {row['glyphB']}  {row['orb']:.1f}°"
            ax_leg.text(
                x_text,
                y,
                txt,
                fontsize=9,
                color="tab:blue",
                transform=ax_leg.transAxes,
                va="center",
                ha="left",
            )
            y -= 0.032

    # spazio tra positivi e negativi
    if aspetti_pos and aspetti_neg:
        y -= 0.03

    # Aspetti difficili
    if aspetti_neg:
        x_text = 0.0
        ax_leg.text(
            x_text,
            y,
            "Aspetti difficili / Challenging aspects",
            fontsize=9,
            fontweight="bold",
            transform=ax_leg.transAxes,
            va="center",
            ha="left",
        )
        y -= 0.04

        for row in aspetti_neg:
            txt = f"{row['glyphA']} {row['glyphAsp']} {row['glyphB']}  {row['orb']:.1f}°"
            ax_leg.text(
                x_text,
                y,
                txt,
                fontsize=9,
                color="tab:red",
                transform=ax_leg.transAxes,
                va="center",
                ha="left",
            )
            y -= 0.032

    fig.tight_layout()
    return _fig_to_base64(fig)


def genera_carta_sinastria(
    pianeti_A_decod: dict,
    pianeti_B_decod: dict,
    aspetti_AB: Optional[List[Dict[str, object]]] = None,
    nome_A: str = "A",
    nome_B: str = "B",
    figsize: Tuple[float, float] = (12, 7),
) -> str:
    """
    Alias di grafico_sinastria per compatibilità con il notebook.
    """
    return grafico_sinastria(
        pianeti_A_decod=pianeti_A_decod,
        pianeti_B_decod=pianeti_B_decod,
        aspetti_AB=aspetti_AB,
        nome_A=nome_A,
        nome_B=nome_B,
        figsize=figsize,
    )
