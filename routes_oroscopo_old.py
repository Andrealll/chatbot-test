# routes_oroscopo.py — AstroBot (oroscopo + oroscopo_ai)

import os
import time
import json
from typing import Any, Dict, List, Optional, Literal

import requests
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

router = APIRouter()

# =========================================================
#  Pesi pianeti per periodo
# =========================================================

PESI_PIANETI_PER_PERIODO: Dict[str, Dict[str, float]] = {
    "giornaliero": {
        "Luna":     1.0,
        "Mercurio": 0.7,
        "Venere":   0.7,
        "Sole":     0.4,
        "Marte":    0.3,
        "Giove":    0.3,
        "Saturno":  0.2,
        "Urano":    0.2,
        "Nettuno":  0.2,
        "Plutone":  0.2,
    },
    "settimanale": {
        "Luna":     0.5,
        "Mercurio": 1.0,
        "Venere":   1.0,
        "Sole":     0.8,
        "Marte":    0.7,
        "Giove":    0.4,
        "Saturno":  0.3,
        "Urano":    0.3,
        "Nettuno":  0.3,
        "Plutone":  0.3,
    },
    "mensile": {
        "Luna":     0.5,
        "Mercurio": 0.7,
        "Venere":   0.7,
        "Sole":     1.0,
        "Marte":    1.0,
        "Giove":    0.7,
        "Saturno":  0.6,
        "Urano":    0.6,
        "Nettuno":  0.6,
        "Plutone":  0.6,
    },
    "annuale": {
        "Luna":     0.0,
        "Mercurio": 0.3,
        "Venere":   0.3,
        "Sole":     0.4,
        "Marte":    0.6,
        "Giove":    0.8,
        "Saturno":  1.0,
        "Urano":    1.0,
        "Nettuno":  1.0,
        "Plutone":  1.0,
    },
}

SOGLIA_PESO = 0.7  # soglia per pianeti/aspetti "attivi"


# =========================================================
#  Modelli Pydantic (endpoint /oroscopo — struct “lite”)
# =========================================================

class Aspetto(BaseModel):
    pianetaA: str
    pianetaB: str
    tipo: str
    orb: float
    peso: float  # peso dell'aspetto (già calcolato dal core, se disponibile)

class OroscopoRequest(BaseModel):
    scope: str  # "giornaliero" | "settimanale" | "mensile" | "annuale"
    tema: Dict[str, Any]
    pianeti_transito: Optional[Dict[str, Dict[str, Any]]] = None
    aspetti: Optional[List[Aspetto]] = None


# =========================================================
#  Modelli Pydantic (endpoint /oroscopo_ai — AI end2end)
# =========================================================

class PianetaPeriodo(BaseModel):
    pianeta: str
    score_periodo: float
    fattore_natale: float
    casa_natale_transito: Optional[int] = None
    prima_occorrenza: Optional[str] = None

class AspettoPeriodo(BaseModel):
    pianeta_transito: str
    pianeta_natale: str
    aspetto: str
    score_rilevanza: float
    orb_min: float
    n_snapshot: int

class OroscopoAIRequest(BaseModel):
    scope: Literal["oroscopo_ai"] = "oroscopo_ai"
    tier: Literal["free", "premium"]
    periodo: Literal["giornaliero", "settimanale", "mensile", "annuale"]
    payload_ai: Dict[str, Any]

class OroscopoAIResponse(BaseModel):
    status: str = "ok"
    scope: str = "oroscopo_ai"
    periodo: str
    tier: str
    elapsed: float
    intensities: Dict[str, float]
    pianeti_periodo: List[PianetaPeriodo]
    aspetti_rilevanti: List[AspettoPeriodo]
    interpretazione_ai: Dict[str, Any]


# =========================================================
#  Utility comuni
# =========================================================

def normalizza_scope(scope: str) -> str:
    scope = (scope or "").lower()
    mapping = {
        "giorno": "giornaliero",
        "giornaliero": "giornaliero",
        "daily": "giornaliero",
        "settimana": "settimanale",
        "settimanale": "settimanale",
        "weekly": "settimanale",
        "mese": "mensile",
        "mensile": "mensile",
        "monthly": "mensile",
        "anno": "annuale",
        "annuale": "annuale",
        "yearly": "annuale",
    }
    return mapping.get(scope, "giornaliero")

def pianeti_rilevanti(scope: str) -> List[str]:
    scope = normalizza_scope(scope)
    pesi_scope = PESI_PIANETI_PER_PERIODO.get(scope, {})
    return [p for p, w in pesi_scope.items() if w >= SOGLIA_PESO]

def calcola_casa_equal(gradi_eclittici: float, asc_mc_case: Dict[str, Any]) -> Optional[int]:
    if not asc_mc_case:
        return None
    asc = asc_mc_case.get("ASC")
    sistema = (asc_mc_case.get("sistema_case") or "").lower()
    if asc is None or sistema != "equal":
        return None
    delta = (float(gradi_eclittici) - float(asc)) % 360.0
    casa = int(delta // 30.0) + 1
    if casa < 1 or casa > 12:
        casa = ((casa - 1) % 12) + 1
    return casa

def estrai_pianeti_periodo(
    pianeti_transito: Dict[str, Dict[str, Any]],
    asc_mc_case: Dict[str, Any],
    scope: str,
) -> List[Dict[str, Any]]:
    scope = normalizza_scope(scope)
    pianeti_sel = pianeti_rilevanti(scope)
    pesi_scope = PESI_PIANETI_PER_PERIODO[scope]

    risultati: List[Dict[str, Any]] = []
    for nome in pianeti_sel:
        if nome not in pianeti_transito:
            continue
        dati = pianeti_transito[nome]
        ge = dati.get("gradi_eclittici")
        casa = calcola_casa_equal(ge, asc_mc_case) if ge is not None else None
        risultati.append({
            "nome": nome,
            "peso_periodo": pesi_scope.get(nome),
            "segno": dati.get("segno"),
            "gradi": dati.get("gradi_segno"),
            "casa": casa,
        })
    return risultati

def filtra_aspetti_rilevanti(aspetti: List[Dict[str, Any]], scope: str, top_n: int = 3) -> List[Dict[str, Any]]:
    scope = normalizza_scope(scope)
    pesi_scope = PESI_PIANETI_PER_PERIODO[scope]
    def pianeta_ok(n: str) -> bool:
        return pesi_scope.get(n, 0.0) >= SOGLIA_PESO
    aspetti_filtrati = [a for a in aspetti if pianeta_ok(a["pianetaA"]) and pianeta_ok(a["pianetaB"])]
    aspetti_ordinati = sorted(aspetti_filtrati, key=lambda a: a.get("peso", 0.0), reverse=True)[:top_n]
    for a in aspetti_ordinati:
        a["peso_pianetaA"] = pesi_scope.get(a["pianetaA"])
        a["peso_pianetaB"] = pesi_scope.get(a["pianetaB"])
    return aspetti_ordinati

def calcola_intensita_stub(aspetti_rilevanti: List[Dict[str, Any]]) -> Dict[str, float]:
    if not aspetti_rilevanti:
        return {"energy": 0.5, "emotions": 0.5, "relationships": 0.5, "work": 0.5, "luck": 0.5}
    somma_pesi = sum(a.get("peso", 0.0) for a in aspetti_rilevanti) or 1.0
    base = min(1.0, somma_pesi / 3.0)
    return {
        "energy": max(0.0, min(1.0, base)),
        "emotions": max(0.0, min(1.0, base * 1.05)),
        "relationships": max(0.0, min(1.0, base * 0.95)),
        "work": max(0.0, min(1.0, base * 0.9)),
        "luck": max(0.0, min(1.0, base * 1.1)),
    }


# =========================================================
#  Endpoint: /oroscopo  (struct “lite”, senza AI)
# =========================================================

@router.post("/oroscopo")
def oroscopo(req: OroscopoRequest):
    t0 = time.time()
    scope = normalizza_scope(req.scope)

    tema = req.tema or {}
    pianeti_natal = tema.get("pianeti_decod", {})
    asc_mc_case = tema.get("asc_mc_case", {})

    pianeti_transito = req.pianeti_transito or pianeti_natal

    pianeti_periodo = estrai_pianeti_periodo(
        pianeti_transito=pianeti_transito,
        asc_mc_case=asc_mc_case,
        scope=scope,
    )

    aspetti_list_dict: List[Dict[str, Any]] = []
    if req.aspetti:
        aspetti_list_dict = [a.model_dump() for a in req.aspetti]

    aspetti_rilevanti = filtra_aspetti_rilevanti(
        aspetti=aspetti_list_dict,
        scope=scope,
        top_n=3,
    )

    intensities = calcola_intensita_stub(aspetti_rilevanti)
    elapsed = round(time.time() - t0, 3)

    return {
        "status": "ok",
        "scope": scope,
        "elapsed": elapsed,
        "intensities": intensities,
        "pianeti_periodo": pianeti_periodo,
        "aspetti_rilevanti": aspetti_rilevanti,
        "interpretazione_AI": None,
    }


# =========================================================
#  Helpers per /oroscopo_ai (consuma payload_ai del core)
# =========================================================

def _extract_period_block(payload_ai: Dict[str, Any], periodo: str) -> Dict[str, Any]:
    periodi = payload_ai.get("periodi") or {}
    if periodo not in periodi:
        raise KeyError(f"Periodo '{periodo}' non presente in payload_ai.periodi.")
    return periodi[periodo]

def _summary_intensities(period_block: Dict[str, Any]) -> Dict[str, float]:
    """
    Riepiloga le intensità del periodo:

    - se esiste 'intensita_mensile' (nuovo mensile) → usa quello;
    - altrimenti media le intensità dei samples in metriche_grafico.
    """
    explic = period_block.get("intensita_mensile")
    if isinstance(explic, dict) and explic:
        return explic

    metriche_grafico = period_block.get("metriche_grafico") or {}
    samples = metriche_grafico.get("samples") or []
    if not samples:
        return {"energy": 0.5, "emotions": 0.5, "relationships": 0.5, "work": 0.5, "luck": 0.5}
    acc: Dict[str, float] = {}
    n = 0
    for s in samples:
        intens = (s.get("metrics") or {}).get("intensities") or {}
        if not intens:
            continue
        for k, v in intens.items():
            acc[k] = acc.get(k, 0.0) + float(v)
        n += 1
    if not n:
        return {"energy": 0.5, "emotions": 0.5, "relationships": 0.5, "work": 0.5, "luck": 0.5}
    return {k: v / n for k, v in acc.items()}

def _summary_aspetti(period_block: Dict[str, Any], max_n: int = 10) -> List[Dict[str, Any]]:
    aspetti = period_block.get("aspetti_rilevanti") or []
    out: List[Dict[str, Any]] = []
    for a in aspetti[:max_n]:
        out.append(
            {
                "pianeta_transito": a.get("pianeta_transito"),
                "pianeta_natale": a.get("pianeta_natale"),
                "aspetto": a.get("aspetto"),
                "score_rilevanza": float(a.get("score_rilevanza", 0.0)),
                "orb_min": float(a.get("orb_min", 0.0)),
                "n_snapshot": int(a.get("n_snapshot", 0)),
            }
        )
    return out

def _summary_pianeti(period_block: Dict[str, Any]) -> List[Dict[str, Any]]:
    return list(period_block.get("pianeti_prevalenti") or [])

def _period_code_from_label(periodo: str) -> str:
    return {
        "giornaliero": "daily",
        "settimanale": "weekly",
        "mensile": "monthly",
        "annuale": "yearly",
    }.get(periodo, "daily")


# =========================================================
#  PROMPT PER GROQ — MULTI-PERIODO / MULTI-TIER
# =========================================================

def _build_messages_giornaliero(
    tier: str,
    meta: Dict[str, Any],
    period_block: Dict[str, Any],
    kb_md: str,
) -> List[Dict[str, str]]:
    """
    Giornaliero:

    FREE:
      {
        "sintesi_giornaliera": "...",
        "capitoli": [
          {
            "id": "oggi",
            "titolo": "Oggi",
            "sintesi": "...",
            "amore": "...",
            "lavoro": "...",
            "crescita_personale": "...",
            "consigli_pratici": ["...", "..."]
          }
        ]
      }

    PREMIUM:
      {
        "sintesi_giornaliera": "...",
        "capitoli": [
          { "id": "mattina", "titolo": "Mattina", ... },
          { "id": "sera", "titolo": "Sera", ... },
          { "id": "domani", "titolo": "Domani", ... }
        ]
      }
    """
    intensities = _summary_intensities(period_block)
    pianeti = _summary_pianeti(period_block)
    aspetti = _summary_aspetti(period_block, max_n=15)

    system_content = """
Sei AstroBot, un assistente di astrologia psicologica moderna.
Scrivi SEMPRE in italiano.

Leggi il JSON che ti invia l'utente e genera un OROSCOPO GIORNALIERO strutturato.

Output richiesto (SEMPLICE E COMPATTO):

{
  "sintesi_giornaliera": "stringa",
  "capitoli": [
    {
      "id": "...",
      "titolo": "stringa",
      "sintesi": "stringa",
      "amore": "stringa",
      "lavoro": "stringa",
      "crescita_personale": "stringa",
      "consigli_pratici": ["...", "..."]
    }
  ]
}

Regole di sottoperiodo:

- Se tier = "free":
  - Usa 1 solo capitolo in "capitoli":
    - id = "oggi"
    - titolo = "Oggi"
  - "sintesi_giornaliera": massimo 3-4 frasi.
  - Nel capitolo:
    - "sintesi": massimo 2 frasi.
    - "amore", "lavoro", "crescita_personale": massimo 2 frasi ciascuno.
    - "consigli_pratici": da 1 a 2 consigli brevi.

- Se tier = "premium":
  - Usa 3 capitoli in "capitoli":
    - id = "mattina", titolo = "Mattina"
    - id = "sera", titolo = "Sera"
    - id = "domani", titolo = "Domani"
  - "sintesi_giornaliera": massimo 4-6 frasi.
  - Ogni capitolo:
    - "sintesi": massimo 2-3 frasi.
    - "amore", "lavoro", "crescita_personale": massimo 2-3 frasi.
    - "consigli_pratici": da 2 a 3 consigli brevi e concreti.

Usa:
- intensita (energy, emotions, relationships, work, luck) per capire dove mettere il focus;
- pianeti_prevalenti e aspetti_rilevanti per citare qualche passaggio astrologico chiave;
- kb_markdown solo come ispirazione concettuale, NON copiarla parola per parola.

DEVI restituire SOLO un oggetto JSON con quella struttura.
Nessun testo fuori dal JSON. Nessun campo extra.
""".strip()

    user_payload = {
        "tier": tier,
        "meta": {
            "nome": meta.get("nome"),
            "citta": meta.get("citta"),
            "data_nascita": meta.get("data_nascita"),
            "ora_nascita": meta.get("ora_nascita"),
            "lang": meta.get("lang", "it"),
        },
        "periodo": {
            "key": "giornaliero",
            "label": period_block.get("label", "Oroscopo di oggi"),
            "date_range": period_block.get("date_range"),
            "intensita": intensities,
            "pianeti_prevalenti": pianeti,
            "aspetti_rilevanti": aspetti,
        },
        "kb_markdown": kb_md,
    }

    return [
        {"role": "system", "content": system_content},
        {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
    ]


def _build_messages_settimanale(
    tier: str,
    meta: Dict[str, Any],
    period_block: Dict[str, Any],
    kb_md: str,
) -> List[Dict[str, str]]:
    """
    Settimanale:

    FREE:
      - 2 capitoli: settimana (lun-ven), weekend

    PREMIUM:
      - 3 capitoli: inizio_settimana, meta_settimana, fine_settimana
    """
    intensities = _summary_intensities(period_block)
    pianeti = _summary_pianeti(period_block)
    aspetti = _summary_aspetti(period_block, max_n=18)

    system_content = """
Sei AstroBot, un assistente di astrologia psicologica moderna.
Scrivi SEMPRE in italiano.

Genera un OROSCOPO SETTIMANALE strutturato.

Output richiesto:

{
  "sintesi_settimanale": "stringa",
  "capitoli": [
    {
      "id": "...",
      "titolo": "stringa",
      "sintesi": "stringa",
      "amore": "stringa",
      "lavoro": "stringa",
      "crescita_personale": "stringa",
      "consigli_pratici": ["...", "..."]
    }
  ]
}

Regole di sottoperiodo:

- Se tier = "free":
  - Usa 2 capitoli:
    1) id = "settimana", titolo = "Da lunedì a venerdì"
    2) id = "weekend",  titolo = "Weekend"
  - "sintesi_settimanale": massimo 4-6 frasi.
  - Ogni capitolo:
    - "sintesi": massimo 2-3 frasi.
    - "amore", "lavoro", "crescita_personale": massimo 2 frasi.
    - "consigli_pratici": da 1 a 2 consigli brevi.

- Se tier = "premium":
  - Usa 3 capitoli:
    1) id = "inizio_settimana", titolo = "Inizio settimana"
    2) id = "meta_settimana",   titolo = "Metà settimana"
    3) id = "fine_settimana",   titolo = "Fine settimana"
  - "sintesi_settimanale": 1-2 paragrafi (max 8 frasi).
  - Ogni capitolo:
    - "sintesi": massimo 3 frasi.
    - "amore", "lavoro", "crescita_personale": massimo 3 frasi ciascuno.
    - "consigli_pratici": da 2 a 4 consigli concreti.

Usa intensita, pianeti_prevalenti, aspetti_rilevanti e kb_markdown come nel giornaliero.
Nessun testo fuori dal JSON. Nessun campo extra.
""".strip()

    user_payload = {
        "tier": tier,
        "meta": {
            "nome": meta.get("nome"),
            "citta": meta.get("citta"),
            "data_nascita": meta.get("data_nascita"),
            "ora_nascita": meta.get("ora_nascita"),
            "lang": meta.get("lang", "it"),
        },
        "periodo": {
            "key": "settimanale",
            "label": period_block.get("label", "Oroscopo della settimana"),
            "date_range": period_block.get("date_range"),
            "intensita": intensities,
            "pianeti_prevalenti": pianeti,
            "aspetti_rilevanti": aspetti,
        },
        "kb_markdown": kb_md,
    }

    return [
        {"role": "system", "content": system_content},
        {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
    ]


def _build_messages_mensile(
    tier: str,
    meta: Dict[str, Any],
    mensile_block: Dict[str, Any],
    kb_md: str,
) -> List[Dict[str, str]]:
    """
    Mensile:

    FREE:
      - 2 capitoli:
        - prima_meta
        - seconda_meta

    PREMIUM:
      - 4 capitoli:
        - prima_decade
        - seconda_decade
        - terza_decade
        - transizione (verso il mese successivo)
    """
    intensita_mensile = mensile_block.get("intensita_mensile", {})
    date_range = mensile_block.get("date_range")
    sottoperiodi_raw = (
        mensile_block.get("sottoperiodi")
        or mensile_block.get("mensile_sottoperiodi")
        or []
    )

    system_content = """
Sei AstroBot, un assistente di astrologia psicologica moderna.
Scrivi SEMPRE in italiano.

Genera un OROSCOPO MENSILE strutturato.

Output richiesto:

{
  "sintesi_mensile": "stringa",
  "capitoli": [
    {
      "id": "...",
      "titolo": "stringa",
      "sintesi": "stringa",
      "amore": "stringa",
      "lavoro": "stringa",
      "crescita_personale": "stringa",
      "consigli_pratici": ["...", "..."]
    }
  ]
}

Regole di sottoperiodo:

- Se tier = "free":
  - Usa 2 capitoli:
    1) id = "prima_meta",   titolo = "Prima metà del mese"
    2) id = "seconda_meta", titolo = "Seconda metà del mese"
  - "sintesi_mensile": massimo 4-6 frasi.
  - Ogni capitolo:
    - "sintesi": massimo 3 frasi.
    - "amore", "lavoro", "crescita_personale": massimo 3 frasi.
    - "consigli_pratici": da 2 a 3 consigli brevi.

- Se tier = "premium":
  - Usa 4 capitoli:
    1) id = "prima_decade",   titolo = "Prima decade (1–10)"
    2) id = "seconda_decade", titolo = "Seconda decade (11–20)"
    3) id = "terza_decade",   titolo = "Terza decade (dal 21 in poi)"
    4) id = "transizione",    titolo = "Transizione verso il mese successivo"
  - "sintesi_mensile": 1-2 paragrafi (max 8-10 frasi).
  - Ogni capitolo:
    - "sintesi": massimo 3 frasi.
    - "amore", "lavoro", "crescita_personale": massimo 3 frasi ciascuno.
    - "consigli_pratici": da 3 a 5 consigli concreti.

Usa:
- "intensita_mensile" per la visione d'insieme.
- Per i capitoli, combina in modo intelligente i sottoperiodi forniti nel JSON (sottoperiodi) e la KB.
- kb_markdown va usata come ispirazione concettuale, NON copiata.

Nessun testo fuori dal JSON. Nessun campo extra.
""".strip()

    sottoperiodi_slim = []
    for sp in sottoperiodi_raw:
        sottoperiodi_slim.append(
            {
                "id": sp.get("id"),
                "titolo": sp.get("label"),
                "date_range": sp.get("date_range"),
                "intensita": sp.get("intensita", {}),
                "pianeti_prevalenti": sp.get("pianeti_prevalenti", []),
                "aspetti_rilevanti": sp.get("aspetti_rilevanti", []),
            }
        )

    user_payload = {
        "tier": tier,
        "meta": {
            "nome": meta.get("nome"),
            "citta": meta.get("citta"),
            "data_nascita": meta.get("data_nascita"),
            "ora_nascita": meta.get("ora_nascita"),
            "lang": meta.get("lang", "it"),
        },
        "periodo": {
            "key": "mensile",
            "label": mensile_block.get("label"),
            "date_range": date_range,
            "intensita_mensile": intensita_mensile,
            "sottoperiodi": sottoperiodi_slim,
        },
        "kb_markdown": kb_md,
    }

    return [
        {"role": "system", "content": system_content},
        {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
    ]


def _build_messages_annuale(
    tier: str,
    meta: Dict[str, Any],
    period_block: Dict[str, Any],
    kb_md: str,
) -> List[Dict[str, str]]:
    """
    Annuale (stessa struttura per free/premium, ma più testo per premium):

    5 capitoli:
    - q1: gennaio-marzo
    - q2: aprile-giugno
    - q3: luglio-settembre
    - q4: ottobre-dicembre
    - integrazione finale
    """
    intensities = _summary_intensities(period_block)
    pianeti = _summary_pianeti(period_block)
    aspetti = _summary_aspetti(period_block, max_n=25)

    system_content = """
Sei AstroBot, un assistente di astrologia psicologica moderna.
Scrivi SEMPRE in italiano.

Genera un OROSCOPO ANNUALE strutturato.

Output richiesto:

{
  "sintesi_annuale": "stringa",
  "capitoli": [
    {
      "id": "...",
      "titolo": "stringa",
      "sintesi": "stringa",
      "amore": "stringa",
      "lavoro": "stringa",
      "crescita_personale": "stringa",
      "consigli_pratici": ["...", "..."]
    }
  ]
}

Struttura dei capitoli (sia free sia premium):

1) id = "q1",         titolo = "Gennaio – Marzo"
2) id = "q2",         titolo = "Aprile – Giugno"
3) id = "q3",         titolo = "Luglio – Settembre"
4) id = "q4",         titolo = "Ottobre – Dicembre"
5) id = "integrazione", titolo = "Sintesi e integrazione dell'anno"

Differenze:

- tier = "free":
  - "sintesi_annuale": massimo 2-3 paragrafi (max ~12 frasi).
  - Ogni capitolo:
    - "sintesi": massimo 3 frasi.
    - "amore", "lavoro", "crescita_personale": massimo 2 frasi ciascuno.
    - "consigli_pratici": da 1 a 3 consigli brevi.

- tier = "premium":
  - "sintesi_annuale": 3-4 paragrafi (max ~18 frasi).
  - Ogni capitolo:
    - "sintesi": massimo 3-4 frasi.
    - "amore", "lavoro", "crescita_personale": massimo 3 frasi ciascuno.
    - "consigli_pratici": da 3 a 5 consigli concreti.

Usa intensita, pianeti_prevalenti, aspetti_rilevanti e kb_markdown come negli altri casi.
Nessun testo fuori dal JSON. Nessun campo extra.
""".strip()

    user_payload = {
        "tier": tier,
        "meta": {
            "nome": meta.get("nome"),
            "citta": meta.get("citta"),
            "data_nascita": meta.get("data_nascita"),
            "ora_nascita": meta.get("ora_nascita"),
            "lang": meta.get("lang", "it"),
        },
        "periodo": {
            "key": "annuale",
            "label": period_block.get("label", "Oroscopo dell'anno"),
            "date_range": period_block.get("date_range"),
            "intensita": intensities,
            "pianeti_prevalenti": pianeti,
            "aspetti_rilevanti": aspetti,
        },
        "kb_markdown": kb_md,
    }

    return [
        {"role": "system", "content": system_content},
        {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
    ]


def _get_max_tokens_for_period(periodo: str, tier: str) -> int:
    """
    Aumenta i max_tokens proporzionalmente per periodo e tier.

    FREE  (più compatti):
      - giornaliero: 280
      - settimanale: 340
      - mensile:    420
      - annuale:    520

    PREMIUM (più spazio):
      - giornaliero: 450
      - settimanale: 650
      - mensile:    850
      - annuale:    950
    """
    periodo = normalizza_scope(periodo)
    tier = (tier or "free").lower()

    if tier == "premium":
        mapping = {
            "giornaliero": 450,
            "settimanale": 650,
            "mensile": 850,
            "annuale": 950,
        }
    else:
        mapping = {
            "giornaliero": 280,
            "settimanale": 340,
            "mensile": 420,
            "annuale": 520,
        }
    return mapping.get(periodo, 350)


def _build_groq_messages(req: OroscopoAIRequest, payload_ai: Dict[str, Any]) -> List[Dict[str, str]]:
    """
    Smista tra:
    - giornaliero
    - settimanale
    - mensile
    - annuale
    con le rispettive strutture di output.
    """
    meta = payload_ai.get("meta") or {}
    kb_md = ((payload_ai.get("kb") or {}).get("combined_markdown")) or ""

    # riduco la KB per sicurezza
    if req.periodo == "mensile" or req.periodo == "annuale":
        kb_md = kb_md[:6000]
    else:
        kb_md = kb_md[:4000]

    periodo = req.periodo
    period_block = _extract_period_block(payload_ai, periodo)

    tier = req.tier.lower()
    if tier not in {"free", "premium"}:
        tier = "free"

    periodo_norm = normalizza_scope(periodo)

    if periodo_norm == "giornaliero":
        return _build_messages_giornaliero(
            tier=tier,
            meta=meta,
            period_block=period_block,
            kb_md=kb_md,
        )
    elif periodo_norm == "settimanale":
        return _build_messages_settimanale(
            tier=tier,
            meta=meta,
            period_block=period_block,
            kb_md=kb_md,
        )
    elif periodo_norm == "mensile":
        return _build_messages_mensile(
            tier=tier,
            meta=meta,
            mensile_block=period_block,
            kb_md=kb_md,
        )
    else:  # annuale (o fallback)
        return _build_messages_annuale(
            tier=tier,
            meta=meta,
            period_block=period_block,
            kb_md=kb_md,
        )



# =========================================================
#  Helper parsing robusto JSON da Groq
# =========================================================

def _parse_groq_json_safely(content: str) -> Dict[str, Any]:
    """
    Prova a ottenere un dict JSON dalla risposta del modello.

    - Prima rimuove eventuali code fence ```json ... ```
    - Poi tenta json.loads diretto
    - Se fallisce, tenta a prendere dal primo '{' all'ultima '}'
    - Se ancora fallisce, ritorna {"raw": content}
    """
    if not content:
        return {}

    text = content.strip()

    # 1) Rimozione blocchi ```...``` (es. ```json\n{ ... }\n```)
    if "```" in text:
        first = text.find("```")
        second = text.find("```", first + 3)
        if second != -1:
            # parte interna tra i due ```
            inner = text[first + 3:second]

            # se c'è una label tipo "json" sulla prima riga, la salto
            inner = inner.lstrip()
            # salta eventuale "json" o simile fino a fine riga
            if inner.lower().startswith("json"):
                # taglia fino al primo newline dopo "json"
                nl_pos = inner.find("\n")
                if nl_pos != -1:
                    inner = inner[nl_pos + 1:]
                else:
                    # tutto su una riga, niente JSON vero
                    inner = ""

            text = inner.strip() or text  # se inner vuoto, tengo l'originale

    # 2) Tentativo diretto di parse
    try:
        return json.loads(text)
    except Exception:
        pass

    # 3) Tentativo: estrai il blocco tra primo '{' e ultima '}'
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        snippet = text[start : end + 1]
        try:
            return json.loads(snippet)
        except Exception:
            pass

    # 4) Fallback finale
    return {"raw": content}

# =========================================================
#  Endpoint: /oroscopo_ai  (usa Groq SENZA response_format)
# =========================================================

@router.post("/oroscopo_ai", response_model=OroscopoAIResponse)
def oroscopo_ai(req: OroscopoAIRequest) -> OroscopoAIResponse:
    start = time.time()

    payload_ai = req.payload_ai
    try:
        period_block = _extract_period_block(payload_ai, req.periodo)
    except KeyError as e:
        raise HTTPException(status_code=400, detail=str(e))

    intensities = _summary_intensities(period_block)
    pianeti = _summary_pianeti(period_block)
    aspetti = _summary_aspetti(period_block, max_n=20)

    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="GROQ_API_KEY non configurata")

    messages = _build_groq_messages(req, payload_ai)

    max_tokens = 650 if req.tier == "premium" else 400

    groq_body = {
        "model": os.environ.get("AI_MODEL", "llama-3.3-70b-versatile"),
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": float(os.environ.get("AI_TEMPERATURE", "0.7")),
        # 👉 NIENTE response_format qui
    }

    try:
        resp = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=groq_body,
            timeout=60,
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Errore chiamata Groq: {e}")

    if resp.status_code != 200:
        raise HTTPException(
            status_code=502,
            detail=f"Groq HTTP {resp.status_code}: {resp.text[:800]}",
        )

    data = resp.json()
    content = (((data.get("choices") or [{}])[0].get("message") or {}).get("content")) or "{}"

    interpretazione = _parse_groq_json_safely(content)
    elapsed = time.time() - start

    return OroscopoAIResponse(
        periodo=req.periodo,
        tier=req.tier,
        elapsed=elapsed,
        intensities=intensities,
        pianeti_periodo=[PianetaPeriodo(**p) for p in pianeti],
        aspetti_rilevanti=[AspettoPeriodo(**a) for a in aspetti],
        interpretazione_ai=interpretazione,
    )
