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
    # payload_ai: quello prodotto da build_oroscopo_payload_ai (core)
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
    # Preferisci intensità mensili esplicite se presenti (nuovo mensile)
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
#  NUOVO: builder messaggi Groq (mensile a capitoli + generico)
# =========================================================

def _build_messages_generico(
    tier: str,
    periodo: str,
    meta: Dict[str, Any],
    period_block: Dict[str, Any],
    kb_md: str,
) -> List[Dict[str, str]]:
    """
    Schema "classico" per giornaliero/settimanale/annuale:

    {
      "sintesi": "...",
      "amore": "...",
      "lavoro": "...",
      "crescita_personale": "...",
      "consigli_pratici": ["...", "..."]
    }
    """
    period_code = _period_code_from_label(periodo)
    intensities = _summary_intensities(period_block)
    pianeti = _summary_pianeti(period_block)
    aspetti = _summary_aspetti(period_block, max_n=20)

    system_content = f"""
Sei AstroBot, un assistente AI di astrologia psicologica moderna.
Parli in italiano chiaro, contemporaneo, con un tono empatico ma concreto,
adatto a un pubblico adulto e professionale (es. LinkedIn, blog).

RICEVI:
- i dati di base della persona (meta)
- un singolo periodo (giornaliero/settimanale/annuale) con:
  - intensità per aree della vita (energy, emotions, relationships, work, luck)
  - transiti e aspetti rilevanti del periodo
  - contenuto di Knowledge Base (markdown) già filtrato

OBIETTIVO:
- Generare un oroscopo PERSONALIZZATO per il periodo.
- Devi usare in modo coerente:
  - le INTENSITÀ: se un punteggio è alto, enfatizza quell'area; se è basso, evidenzia possibili sfide.
  - i TRANSITI: cita alcuni pianeti/aspetti rilevanti e collegali al vissuto psicologico.
  - la KNOWLEDGE BASE: usala come ispirazione, non copiarla parola per parola.

STILE:
- Niente toni fatalistici o catastrofici.
- Sii incoraggiante ma realistico.
- Evita frasi troppo vaghe o da "oroscopo da giornale".
- Non dare consigli medici, finanziari o legali.

DIFFERENZA FREE vs PREMIUM:

- TIER = "free":
  - Testo complessivo più BREVE.
  - Max 2 paragrafi complessivi sommando sintesi + amore + lavoro + crescita_personale.
  - 1 o 2 consigli_pratici brevi e molto concreti.

- TIER = "premium":
  - Testo più RICCO e strutturato.
  - Ogni sezione (sintesi, amore, lavoro, crescita_personale) deve avere contenuto distinto e più sviluppato.
  - consigli_pratici deve essere una lista di 3-5 punti operativi, specifici.

FORMATO DI OUTPUT (SOLO JSON):

Devi restituire SOLO un oggetto JSON con struttura ESATTA:

{{
  "sintesi": "stringa con la visione generale del periodo",
  "amore": "stringa focalizzata su amore/relazioni",
  "lavoro": "stringa focalizzata su lavoro/carriera/denaro",
  "crescita_personale": "stringa focalizzata su benessere interiore e sviluppo personale",
  "consigli_pratici": [
    "consiglio 1",
    "consiglio 2"
  ]
}}

IMPORTANTISSIMO:
- Nessun testo fuori dal JSON.
- Nessun commento, spiegazione o markup aggiuntivo.
- Nessun campo extra nel JSON, solo quelli indicati.
- Scrivi SEMPRE in italiano.
- Rispetta le differenze di lunghezza tra FREE e PREMIUM.
""".strip()

    user_payload = {
        "tier": tier,
        "period_code": period_code,
        "meta": {
            "nome": meta.get("nome"),
            "citta": meta.get("citta"),
            "data_nascita": meta.get("data_nascita"),
            "ora_nascita": meta.get("ora_nascita"),
            "lang": meta.get("lang", "it"),
        },
        "periodo": {
            "key": periodo,
            "label": period_block.get("label", periodo),
            "date_range": period_block.get("date_range"),
            "intensita": intensities,
            "pianeti_prevalenti": pianeti,
            "aspetti_rilevanti": aspetti,
        },
        "kb_markdown": kb_md,
    }

    user_content = (
        "Di seguito trovi il contesto per generare l'oroscopo.\n\n"
        "CONTESTO_JSON:\n"
        + json.dumps(user_payload, ensure_ascii=False)
    )

    return [
        {"role": "system", "content": system_content},
        {"role": "user", "content": user_content},
    ]


def _build_messages_mensile(
    tier: str,
    meta: Dict[str, Any],
    mensile_block: Dict[str, Any],
    kb_md: str,
) -> List[Dict[str, str]]:
    """
    Caso specifico: PERIODO MENSILE con sottoperiodi.

    Schema di OUTPUT richiesto:

    {
      "sintesi_mensile": "...",
      "capitoli": [
        {
          "id": "inizio_mese",
          "titolo": "Inizio mese (1–10)",
          "sintesi": "...",
          "amore": "...",
          "lavoro": "...",
          "crescita_personale": "...",
          "consigli_pratici": ["...", "..."]
        },
        ...
      ]
    }
    """
    intensita_mensile = mensile_block.get("intensita_mensile", {})
    date_range = mensile_block.get("date_range")
    sottoperiodi_raw = mensile_block.get("sottoperiodi") or mensile_block.get("mensile_sottoperiodi") or []

    system_content = f"""
Sei AstroBot, un assistente AI di astrologia psicologica moderna.
Parli in italiano chiaro, contemporaneo, con un tono empatico ma concreto,
adatto a un pubblico adulto e professionale (es. LinkedIn, blog).

RICEVI:
- i dati di base della persona (meta)
- la fotografia di un PERIODO MENSILE,
  con:
  - intensità complessive del mese (intensita_mensile)
  - suddivisione del mese in 4 sottoperiodi (capitoli):
    * inizio_mese (1–10)
    * meta_mese (11–20)
    * fine_mese (21–fine mese)
    * inizio_mese_successivo (es. 1–7 del mese dopo)
  - per ogni sottoperiodo:
    * intensità specifiche
    * pianeti_prevalenti (transiti chiave)
    * aspetti_rilevanti (transito → pianeta natale)
  - un testo di Knowledge Base (markdown) già filtrato sui transiti principali.

OBIETTIVO:
- Scrivere un OROSCOPO MENSILE STRUTTURATO in 5 parti:
  1) una SINTESI_MENSILE che riassuma le tendenze generali del mese,
     integrando intensità_mensile e i temi ricorrenti dei sottoperiodi.
  2) 4 CAPITOLI, uno per ogni sottoperiodo:
       - inizio_mese
       - meta_mese
       - fine_mese
       - inizio_mese_successivo

Per ogni CAPITOLO devi:
- usare soprattutto i transiti e le intensità di quel sottoperiodo;
- evidenziare cosa cambia rispetto agli altri momenti del mese;
- parlare nelle sezioni:
    * sintesi
    * amore (relazioni, vita privata)
    * lavoro (carriera, progetti, denaro)
    * crescita_personale (benessere interiore, mindset, sviluppo personale)
    * consigli_pratici (1 lista di azioni concrete)

UTILIZZO di INTENSITÀ, TRANSITI e KB:
- Le INTENSITÀ guidano quanto enfatizzare un ambito (se alto → molto presente, se basso → area più neutra o sfidante).
- I TRANSITI (pianeti_prevalenti + aspetti_rilevanti) danno colore astrologico:
  cita alcuni transiti significativi, ma non elencarli tutti in modo meccanico.
- La KNOWLEDGE BASE in markdown serve per approfondire il significato dei transiti:
  leggila "mentalmente", ma non copiarla parola per parola; riformula con stile naturale.

STILE:
- Linguaggio chiaro, moderno, niente toni fatalistici o catastrofici.
- Sii incoraggiante, ma non promettere miracoli.
- Evita frasi da "oroscopo da giornale".
- Non dare consigli medici, finanziari o legali.
- Adatto a un pubblico che potrebbe leggere su LinkedIn o su un blog di crescita personale.

DIFFERENZA FREE vs PREMIUM:

- TIER = "free":
  - Testo complessivo PIÙ BREVE.
  - "sintesi_mensile": massimo 1 paragrafo.
  - Per ogni capitolo:
      * "sintesi" breve (2-3 frasi) che unisce amore/lavoro/crescita in modo sintetico.
      * campi "amore", "lavoro", "crescita_personale" possono essere molto brevi o coincidere con la sintesi.
      * "consigli_pratici": 1 o 2 frasi al massimo.

- TIER = "premium":
  - Testo PIÙ RICCO e STRUTTURATO.
  - "sintesi_mensile": può avere 1-2 paragrafi, con una visione ampia.
  - Per ogni capitolo:
      * "sintesi": paragrafo dedicato.
      * "amore": paragrafo dedicato.
      * "lavoro": paragrafo dedicato.
      * "crescita_personale": paragrafo dedicato.
      * "consigli_pratici": lista di 3-5 punti molto concreti, azionabili.

FORMATO DI OUTPUT (SOLO JSON):

Devi restituire SOLO un oggetto JSON con struttura ESATTA:

{{
  "sintesi_mensile": "stringa con visione generale del mese",
  "capitoli": [
    {{
      "id": "inizio_mese",
      "titolo": "Inizio mese (1–10)",
      "sintesi": "testo sintetico per il sottoperiodo",
      "amore": "testo focalizzato sulle relazioni in quel sottoperiodo",
      "lavoro": "testo focalizzato su lavoro/denaro in quel sottoperiodo",
      "crescita_personale": "testo focalizzato su benessere e sviluppo interiore",
      "consigli_pratici": [
        "consiglio 1",
        "consiglio 2"
      ]
    }}
  ]
}}

IMPORTANTISSIMO:
- Nessun testo fuori dal JSON.
- Nessun commento, spiegazione o markup aggiuntivo.
- Nessun campo extra nel JSON, solo quelli indicati.
- Scrivi SEMPRE in italiano.
- Rispetta le differenze tra FREE e PREMIUM nella lunghezza e nel dettaglio.
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

    user_content = (
        "Di seguito trovi il contesto per generare l'oroscopo mensile strutturato.\n\n"
        "CONTESTO_JSON:\n"
        + json.dumps(user_payload, ensure_ascii=False)
    )

    return [
        {"role": "system", "content": system_content},
        {"role": "user", "content": user_content},
    ]


def _build_groq_messages(req: OroscopoAIRequest, payload_ai: Dict[str, Any]) -> List[Dict[str, str]]:
    """
    Smista tra:
    - builder generico (giornaliero/settimanale/annuale)
    - builder mensile a 4 capitoli
    """
    meta = payload_ai.get("meta") or {}
    kb_md = ((payload_ai.get("kb") or {}).get("combined_markdown")) or ""
    kb_md = kb_md[:16000]  # safety

    periodo = req.periodo
    period_code = _period_code_from_label(periodo)
    period_block = _extract_period_block(payload_ai, periodo)

    tier = req.tier.lower()
    if tier not in {"free", "premium"}:
        tier = "free"

    if period_code == "monthly":
        # caso speciale: mensile a 4 capitoli
        return _build_messages_mensile(
            tier=tier,
            meta=meta,
            mensile_block=period_block,
            kb_md=kb_md,
        )
    else:
        # caso generico: schema classico
        return _build_messages_generico(
            tier=tier,
            periodo=periodo,
            meta=meta,
            period_block=period_block,
            kb_md=kb_md,
        )


# =========================================================
#  Endpoint: /oroscopo_ai  (usa Groq con response_format=json_object)
# =========================================================

@router.post("/oroscopo_ai", response_model=OroscopoAIResponse)
def oroscopo_ai(req: OroscopoAIRequest) -> OroscopoAIResponse:
    start = time.time()

    payload_ai = req.payload_ai
    try:
        period_block = _extract_period_block(payload_ai, req.periodo)
    except KeyError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Intensità/pianeti/aspetti di riepilogo (per risposta API)
    intensities = _summary_intensities(period_block)
    pianeti = _summary_pianeti(period_block)
    aspetti = _summary_aspetti(period_block, max_n=20)

    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="GROQ_API_KEY non configurata")

    messages = _build_groq_messages(req, payload_ai)

    groq_body = {
        "model": os.environ.get("AI_MODEL", "llama-3.3-70b-versatile"),
        "messages": messages,
        "max_tokens": 900 if req.tier == "premium" else 450,
        "temperature": float(os.environ.get("AI_TEMPERATURE", "0.7")),
        "response_format": {"type": "json_object"},
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

    try:
        interpretazione = json.loads(content)
    except Exception:
        interpretazione = {"raw": content}  # fallback

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
