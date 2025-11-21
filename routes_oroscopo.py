# =========================================================
#  routes_oroscopo.py — AstroBot (oroscopo + oroscopo_ai)
#  Versione rifatta con unico super-prompt /oroscopo_ai
# =========================================================
import os
import time
import json
from typing import Any, Dict, List, Optional, Literal
import requests
from anthropic import Anthropic, APIStatusError
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from astrobot_core.oroscopo_payload_ai import (
    AI_ENTITY_LIMITS,
    DEFAULT_PERIOD_KEY,
    DEFAULT_TIER,
)




router = APIRouter()

# =========================================================
#  Pesi pianeti per periodo (rimangono IDENTICI)
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

SOGLIA_PESO = 0.7

# =========================================================
#  Modelli Pydantic (rimangono IDENTICI)
# =========================================================

class Aspetto(BaseModel):
    pianetaA: str
    pianetaB: str
    tipo: str
    orb: float
    peso: float

class OroscopoRequest(BaseModel):
    scope: str
    tema: Dict[str, Any]
    pianeti_transito: Optional[Dict[str, Dict[str, Any]]] = None
    aspetti: Optional[List[Aspetto]] = None

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
#  Utility comuni (rimangono identiche)
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

    out: List[Dict[str, Any]] = []
    for nome in pianeti_sel:
        if nome not in pianeti_transito:
            continue
        dati = pianeti_transito[nome]
        ge = dati.get("gradi_eclittici")
        casa = calcola_casa_equal(ge, asc_mc_case) if ge is not None else None
        out.append({
            "nome": nome,
            "peso_periodo": pesi_scope.get(nome),
            "segno": dati.get("segno"),
            "gradi": dati.get("gradi_segno"),
            "casa": casa,
        })
    return out


def filtra_aspetti_rilevanti(aspetti: List[Dict[str, Any]], scope: str, top_n: int = 3) -> List[Dict[str, Any]]:
    scope = normalizza_scope(scope)
    pesi_scope = PESI_PIANETI_PER_PERIODO[scope]

    def ok(n: str) -> bool:
        return pesi_scope.get(n, 0.0) >= SOGLIA_PESO

    filtrati = [a for a in aspetti if ok(a["pianetaA"]) and ok(a["pianetaB"])]
    ordinati = sorted(filtrati, key=lambda a: a.get("peso", 0.0), reverse=True)[:top_n]

    for a in ordinati:
        a["peso_pianetaA"] = pesi_scope.get(a["pianetaA"])
        a["peso_pianetaB"] = pesi_scope.get(a["pianetaB"])
    return ordinati


def calcola_intensita_stub(aspetti_rilevanti: List[Dict[str, Any]]) -> Dict[str, float]:
    if not aspetti_rilevanti:
        return {"energy": 0.5, "emotions": 0.5, "relationships": 0.5, "work": 0.5, "luck": 0.5}
    somma = sum(a.get("peso", 0.0) for a in aspetti_rilevanti) or 1.0
    base = min(1.0, somma / 3.0)
    return {
        "energy": base,
        "emotions": min(1.0, base * 1.05),
        "relationships": min(1.0, base * 0.95),
        "work": min(1.0, base * 0.9),
        "luck": min(1.0, base * 1.1),
    }


# =========================================================
#  /oroscopo (lite) – invariato
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
#  Helpers per /oroscopo_ai
# =========================================================

def _extract_period_block(payload_ai: Dict[str, Any], periodo: str) -> Dict[str, Any]:
    periodi = payload_ai.get("periodi") or {}
    if periodo not in periodi:
        raise KeyError(f"Periodo '{periodo}' non presente in payload_ai.periodi.")
    return periodi[periodo]


def _summary_intensities(period_block: Dict[str, Any]) -> Dict[str, float]:
    explic = period_block.get("intensita_mensile")
    if isinstance(explic, dict) and explic:
        return explic

    metriche_grafico = period_block.get("metriche_grafico") or {}
    samples = metriche_grafico.get("samples") or []
    if not samples:
        return {"energy": 0.5, "emotions": 0.5, "relationships": 0.5, "work": 0.5, "luck": 0.5}

    acc = {}
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
        out.append({
            "pianeta_transito": a.get("pianeta_transito"),
            "pianeta_natale": a.get("pianeta_natale"),
            "aspetto": a.get("aspetto"),
            "score_rilevanza": float(a.get("score_rilevanza", 0.0)),
            "orb_min": float(a.get("orb_min", 0.0)),
            "n_snapshot": int(a.get("n_snapshot", 0)),
        })
    return out


def _summary_pianeti(period_block: Dict[str, Any]) -> List[Dict[str, Any]]:
    return list(period_block.get("pianeti_prevalenti") or [])


def _map_periodo_to_period_code(periodo: str) -> str:
    mapping = {
        "giornaliero": "daily",
        "settimanale": "weekly",
        "mensile": "monthly",
        "annuale": "yearly",
    }
    return mapping.get(periodo, "daily")

def _strip_kb_occurrence_details(kb_markdown: str) -> str:
    """
    Rimuove dal markdown KB il blocco:
    '### Dettagli delle occorrenze principali'
    per evitare di inviare a Claude tutte le occorrenze ripetute
    dello stesso aspetto (che mangiano un sacco di token).
    """
    if not kb_markdown:
        return ""

    marker = "### Dettagli delle occorrenze principali"
    idx = kb_markdown.find(marker)
    if idx == -1:
        # Nessun blocco "Dettagli..." trovato -> ritorno tutto com'è
        return kb_markdown

    # Teniamo solo la parte prima del blocco di dettagli
    head = kb_markdown[:idx].rstrip()
    return head


def _build_messages_oroscopo_ai_unificato(
    meta: Dict[str, Any],
    periodo: str,
    tier: str,
    period_block: Dict[str, Any],
    kb_markdown: str,
    aspetti_rilevanti: List[Dict[str, Any]],
):
    """
    Versione LIGHT: prepara un JSON compatto e leggibile per il modello.
    - riduce KB
    - riduce e normalizza gli aspetti
    - non passa tema, metriche_grafico, occorrenze grezze
    """

    # 1) Meta "minimal"
    meta_light = {
        "nome": meta.get("nome"),
        "citta": meta.get("citta_nascita") or meta.get("citta"),
        "data_nascita": meta.get("data_nascita"),
        "ora_nascita": meta.get("ora_nascita"),
        "tier": tier,
        "lang": meta.get("lang", "it"),
    }

    # 2) Info periodo
    period_info = {
        "code": periodo,
        "label": period_block.get("label"),
        "range": period_block.get("date_range", {}),
    }

    # 3) Limiti per questo periodo/tier
    limits = AI_ENTITY_LIMITS.get(
        (periodo, tier),
        AI_ENTITY_LIMITS[(DEFAULT_PERIOD_KEY, DEFAULT_TIER)],
    )
    max_aspetti = limits["max_aspetti"]
    max_pianeti = limits["max_pianeti_prevalenti"]
    max_kb_chars = limits["max_kb_chars"]

    # 4) Pianeti prevalenti – solo i primi N
    pianeti_prev_raw = period_block.get("pianeti_prevalenti") or []
    pianeti_prev: List[Dict[str, Any]] = []
    for p in pianeti_prev_raw[:max_pianeti]:
        pianeti_prev.append({
            "pianeta": p.get("pianeta"),
            "casa_natale_transito": p.get("casa_natale_transito"),
            "tema": p.get("tema") or "",
            "peso": p.get("score_periodo"),
        })

    contesto_periodo = {
        "trend_generale": period_block.get("trend_generale", ""),
        "pianeti_prevalenti": pianeti_prev,
    }

    # 5) Aspetti chiave – normalizzati e tagliati
    aspetti_light: List[Dict[str, Any]] = []
    for a in (aspetti_rilevanti or [])[:max_aspetti]:
        aspetti_light.append({
            "chiave": a.get("chiave"),
            "pianeta_transito": a.get("pianeta_transito"),
            "pianeta_natale": a.get("pianeta_natale"),
            "aspetto": a.get("aspetto"),
            "intensita_media": a.get("score_rilevanza"),
            "tema": a.get("tema") or "",
        })

    # 6) KB ridotta per caratteri
    kb_clean = _strip_kb_occurrence_details(kb_markdown or "")
    kb_short = (kb_clean)[:max_kb_chars]
    kb_struct = {
        "markdown": kb_short,
    }

    # 7) Payload light finale per il modello
    user_payload_light = {
        "meta": meta_light,
        "periodo": period_info,
        "contesto_periodo": contesto_periodo,
        "aspetti_chiave": aspetti_light,
        "kb": kb_struct,
        "period_code": _map_periodo_to_period_code(periodo),
        "tier": tier,
    }

    system_prompt = SUPER_PROMPT_OROSCOPO_AI.strip()

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": json.dumps(user_payload_light, ensure_ascii=False)},
    ]



# 🚨 il SUPER PROMPT va importato qui come stringa
SUPER_PROMPT_OROSCOPO_AI = """
RUOLO
Sei AstroBot AI, specializzato in astrologia psicologica, evolutiva e pratica.
Generi oroscopi PERSONALIZZATI usando solo i dati forniti.
Restituisci SEMPRE e SOLO un JSON valido, senza testo esterno.

======================================================================
1. INPUT JSON (LIGHT)
======================================================================

Ricevi un unico messaggio "user" con JSON:

{
  "meta": {
    "nome": string | null,
    "citta": string | null,
    "data_nascita": string | null,
    "ora_nascita": string | null,
    "tier": "free" | "premium",
    "lang": "it" | "en" | "es"
  },
  "periodo": {
    "code": "giornaliero" | "settimanale" | "mensile" | "annuale",
    "label": string | null,
    "range": { "start": string | null, "end": string | null }
  },
  "contesto_periodo": {
    "trend_generale": string | null,
    "pianeti_prevalenti": [
      {
        "pianeta": string,
        "casa_natale_transito": int | null,
        "tema": string,     // significato pratico
        "peso": float | null
      },
      ...
    ]
  },
  "aspetti_chiave": [
    {
      "chiave": string,
      "pianeta_transito": string,
      "pianeta_natale": string,
      "aspetto": "trigono" | "quadratura" | "sestile" | "opposizione" | "congiunzione",
      "intensita_media": float | null,
      "tema": string       // significato pratico
    },
    ...
  ],
  "kb": {
    "markdown": string    // testo sintetico dalla KB, già tagliato
  },
  "period_code": "daily" | "weekly" | "monthly" | "yearly",
  "tier": "free" | "premium"
}

Non inventare campi mancanti: se qualcosa non c'è, semplicemente non usarlo.

======================================================================
2. MULTILINGUA (meta.lang)
======================================================================

Scrivi TUTTO il testo (sintesi, capitoli, consigli, CTA) nella lingua:

- "it" → italiano
- "en" → inglese
- "es" → spagnolo
- altro → usa italiano

CTA sempre nella stessa lingua del resto del testo.

======================================================================
3. STRUTTURA GENERALE DELL'OUTPUT
======================================================================

Chiave di sintesi a seconda di period_code:

- daily   → "sintesi_giornaliera"
- weekly  → "sintesi_settimanale"
- monthly → "sintesi_mensile"
- yearly  → "sintesi_annuale"

Struttura base:

{
  "<chiave_sintesi>": string,
  "capitoli": [
    {
      "id": string,
      "titolo": string,
      "sintesi": string,
      "amore": string,
      "lavoro": string,
      "crescita_personale": string,
      "consigli_pratici": [ string, ... ]
    },
    ...
  ],
  ... eventuali chiavi aggiuntive (es. sottoperiodi_premium, cta) ...
}

Niente markdown, niente testo esterno al JSON.

======================================================================
4. PRIORITÀ CONTENUTI ASTROLOGICI
======================================================================

1) TRANSITI (aspetti_chiave)
- Fonte principale dell’interpretazione.
- Ogni aspetto ha già:
  - pianeta_transito, pianeta_natale, aspetto, intensita_media, tema (significato).
- Integra in frasi naturali: descrivi effetti su umore, relazioni, lavoro, crescita personale.
- NON elencare aspetti in modo tecnico, se non in 1–2 frasi mirate.

2) PIANETI PREVALENTI (contesto_periodo.pianeti_prevalenti)
- Usali come "sfondo" del periodo.
- Massimo 1–2 riferimenti espliciti per testo.
- Parti dal campo "tema" e collegalo a situazioni concrete (amicizie, lavoro, famiglia, studio, ecc.).

3) KB (kb.markdown)
- Usala per arricchire il vocabolario e i significati.
- Non copiare frasi intere: parafrasa.
- Se la KB è vuota o corta, lavora comunque con transiti e pianeti_prevalenti.

4) Non inventare:
- Non introdurre pianeti/aspetti/case non presenti in aspetti_chiave o pianeti_prevalenti.
- Puoi usare formulazioni generiche ("energia di rinnovamento", "focus su comunicazione") ma senza dati tecnici falsi.

======================================================================
5. LESSICO E STILE
======================================================================

- Termini tecnici ammessi per gli aspetti:
  - trigono, quadratura, sestile, opposizione, congiunzione.
- Vietate forme inventate (es. "trigonatura", "quadraturatura").
- Tono:
  - empatico, realistico, non fatalista;
  - incoraggiante ma non infantile;
  - orientato alla responsabilità personale.
- Evita:
  - promesse assolute ("succederà sicuramente");
  - contenuti medici/sanitari;
  - consigli finanziari troppo specifici.
- Consigli pratici:
  - frasi azionabili ("scrivi...", "parla con...", "prenditi un momento per...");
  - evita consigli vaghi tipo "pensa positivo" senza contesto.

======================================================================
6. DIFFERENZA FREE VS PREMIUM
======================================================================

- FREE:
  - testo più corto;
  - spesso 1 solo capitolo teaser;
  - presenza di CTA (call to action) verso la versione premium;
  - deve dare valore ma far capire che esistono dettagli aggiuntivi.

- PREMIUM:
  - testo più lungo e dettagliato;
  - struttura per sottoperiodi (giorno / settimana / mese / anno);
  - nessuna CTA commerciale.

======================================================================
7. DAILY (period_code == "daily")
======================================================================

-----------------------------
7.1 DAILY – FREE
-----------------------------

Struttura:

{
  "sintesi_giornaliera": string,
  "capitoli": [
    {
      "id": "oggi",
      "titolo": "Oggi",
      "sintesi": string,
      "amore": string,
      "lavoro": string,
      "crescita_personale": string,
      "consigli_pratici": [ string, string ]
    }
  ]
}

Lunghezze:
- sintesi_giornaliera: ~40–70 parole.
- capitolo.sintesi: ~60–90 parole.
- amore/lavoro/crescita_personale: 2–4 frasi brevi ciascuno.
- consigli_pratici: esattamente 2 frasi brevi.

-----------------------------
7.2 DAILY – PREMIUM
-----------------------------

Struttura:

- Un capitolo per ogni sottoperiodo (es. mattina, pomeriggio, sera/domani).
- Se i sottoperiodi non sono disponibili, usa 2 capitoli: "mattina" e "sera".

Formato:

{
  "sintesi_giornaliera": string,
  "capitoli": [
    {
      "id": "<sottoperiodo_id>",
      "titolo": "<sottoperiodo_label>",
      "sintesi": string,
      "amore": string,
      "lavoro": string,
      "crescita_personale": string,
      "consigli_pratici": [ string, ... ]
    },
    ...
  ]
}

Lunghezze:
- sintesi_giornaliera: ~80–120 parole.
- capitolo.sintesi: ~90–140 parole.
- amore/lavoro/crescita_personale: 3–6 frasi ciascuno.
- consigli_pratici: 3–4 frasi per capitolo.

======================================================================
8. WEEKLY (period_code == "weekly")
======================================================================

-----------------------------
8.1 WEEKLY – FREE (TEASER)
-----------------------------

Struttura:

{
  "sintesi_settimanale": string,
  "capitoli": [
    {
      "id": "settimana_teaser",
      "titolo": "Panoramica della settimana",
      "sintesi": string,
      "amore": string,
      "lavoro": string,
      "crescita_personale": string,
      "consigli_pratici": [ string ]
    }
  ],
  "sottoperiodi_premium": [
    { "id": "inizio_settimana", "titolo": "Inizio settimana" },
    { "id": "meta_settimana",   "titolo": "Metà settimana" },
    { "id": "weekend",          "titolo": "Weekend" }
  ],
  "cta": {
    "testo": string,
    "tipo": "upgrade_weekly_premium",
    "token_type": "weekly_premium",
    "url": null
  }
}

Regole sintesi_settimanale (3 frasi):
- Deve contenere ESATTAMENTE 3 frasi brevi.
- Totale: ~50–80 parole.
- Le 3 frasi devono:
  1) descrivere il tono generale della settimana;
  2) accennare ai temi principali (amore/lavoro/crescita);
  3) suggerire che nella versione premium ci sono dettagli per fasi diverse.

Lunghezze capitolo teaser:
- sintesi: ~40–60 parole.
- amore/lavoro/crescita_personale: 20–35 parole ciascuno.
- consigli_pratici: esattamente 1 frase (< 20 parole).
- cta.testo: 1 frase, 15–25 parole.

-----------------------------
8.2 WEEKLY – PREMIUM
-----------------------------

Struttura:

- Un capitolo per ogni sottoperiodo disponibile (es. inizio_settimana, meta_settimana, weekend).

{
  "sintesi_settimanale": string,
  "capitoli": [
    {
      "id": "<sottoperiodo_id>",
      "titolo": "<sottoperiodo_label>",
      "sintesi": string,
      "amore": string,
      "lavoro": string,
      "crescita_personale": string,
      "consigli_pratici": [ string, ... ]
    },
    ...
  ]
}

Lunghezze:
- sintesi_settimanale: ~130–200 parole.
- capitolo.sintesi: ~120–180 parole.
- amore/lavoro/crescita_personale: 4–7 frasi ciascuno.
- consigli_pratici: 3–5 frasi per capitolo.
- Nessuna CTA commerciale.

======================================================================
9. MONTHLY (period_code == "monthly")
======================================================================

-----------------------------
9.1 MONTHLY – FREE (TEASER)
-----------------------------

Struttura:

{
  "sintesi_mensile": string,
  "capitoli": [
    {
      "id": "mese_teaser",
      "titolo": "Panoramica del mese",
      "sintesi": string,
      "amore": string,
      "lavoro": string,
      "crescita_personale": string,
      "consigli_pratici": [ string ]
    }
  ],
  "sottoperiodi_premium": [
    { "id": "decade_1", "titolo": "Prima decade (1–10)" },
    { "id": "decade_2", "titolo": "Seconda decade (11–20)" },
    { "id": "decade_3", "titolo": "Terza decade (21–31)" }
  ],
  "cta": {
    "testo": string,
    "tipo": "upgrade_monthly_premium",
    "token_type": "monthly_premium",
    "url": null
  }
}

Regole sintesi_mensile (5 frasi):
- Deve contenere ESATTAMENTE 5 frasi brevi.
- Totale: ~60–90 parole.
- Le 5 frasi devono:
  1) descrivere il clima generale del mese;
  2) citare i principali focus (emotivi, relazionali, lavorativi);
  3) far intuire che la versione premium offre analisi giorno per giorno o per decadi.

Lunghezze capitolo teaser:
- sintesi: ~50–70 parole.
- amore/lavoro/crescita_personale: 25–40 parole ciascuno.
- consigli_pratici: esattamente 1 frase (< 20 parole).
- cta.testo: 15–25 parole.

-----------------------------
9.2 MONTHLY – PREMIUM
-----------------------------

Struttura:

- Un capitolo per ogni decade (decade_1, decade_2, decade_3).

{
  "sintesi_mensile": string,
  "capitoli": [
    {
      "id": "decade_1" | "decade_2" | "decade_3",
      "titolo": string,
      "sintesi": string,
      "amore": string,
      "lavoro": string,
      "crescita_personale": string,
      "consigli_pratici": [ string, ... ]
    },
    ...
  ]
}

Lunghezze:
- sintesi_mensile: ~200–300 parole.
- capitolo.sintesi: ~160–230 parole.
- amore/lavoro/crescita_personale: 4–8 frasi ciascuno.
- consigli_pratici: 4–6 frasi per capitolo.

======================================================================
10. YEARLY (period_code == "yearly")
======================================================================

-----------------------------
10.1 YEARLY – FREE (TEASER)
-----------------------------

Struttura:

{
  "sintesi_annuale": string,
  "capitoli": [
    {
      "id": "anno_teaser",
      "titolo": "Panoramica dell'anno",
      "sintesi": string,
      "amore": string,
      "lavoro": string,
      "crescita_personale": string,
      "consigli_pratici": [ string ]
    }
  ],
  "sottoperiodi_premium": [
    { "id": "stagione_1", "titolo": "Inverno / Inizio anno" },
    { "id": "stagione_2", "titolo": "Primavera" },
    { "id": "stagione_3", "titolo": "Estate" },
    { "id": "stagione_4", "titolo": "Autunno / Fine anno" }
  ],
  "cta": {
    "testo": string,
    "tipo": "upgrade_annual_premium",
    "token_type": "annual_premium",
    "url": null
  }
}

Regole sintesi_annuale (7 frasi):
- Deve contenere ESATTAMENTE 7 frasi brevi.
- Totale: ~70–120 parole.
- Le 7 frasi devono:
  1) spiegare il tema centrale dell'anno;
  2) indicare come si distribuiscono le energie principali;
  3) citare sinteticamente amore, lavoro e crescita personale;
  4) suggerire che la versione premium analizza ogni stagione/trimestre in profondità.

Lunghezze capitolo teaser:
- sintesi: ~30–50 parole.
- amore/lavoro/crescita_personale: 20–35 parole ciascuno.
- consigli_pratici: esattamente 1 frase (< 20 parole).
- cta.testo: 15–25 parole.

-----------------------------
10.2 YEARLY – PREMIUM
-----------------------------

Struttura:

- Un capitolo per ogni stagione o trimestre (almeno 4, massimo 6 capitoli).

{
  "sintesi_annuale": string,
  "capitoli": [
    {
      "id": "<stagione_id>",
      "titolo": "<stagione o trimestre>",
      "sintesi": string,
      "amore": string,
      "lavoro": string,
      "crescita_personale": string,
      "consigli_pratici": [ string, ... ]
    },
    ...
  ]
}

Lunghezze:
- sintesi_annuale: ~250–400 parole.
- capitolo.sintesi: ~200–300 parole.
- amore/lavoro/crescita_personale: 5–9 frasi ciascuno.
- consigli_pratici: 4–7 frasi per capitolo.

======================================================================
11. VINCOLO FINALE
======================================================================

OUTPUT FINALE:
- restituisci SOLO il JSON;
- nessun testo prima o dopo;
- nessun markdown.
"""


# =========================================================
#  Chiamata Claude (Anthropic) — JSON via prompt
# =========================================================

def _call_claude_json(messages: List[Dict[str, str]], model: str, max_tokens: int, temperature: float):
    """
    Chiamata a Claude (Anthropic) usando il super-prompt già costruito.
    Ritorna JSON valido (proviamo parse + fallback pulizia) oppure lancia HTTPException.
    """

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="ANTHROPIC_API_KEY non configurata")

    # I messages che arrivano da _build_groq_messages sono:
    # [
    #   {"role": "system", "content": <SUPER_PROMPT_OROSCOPO_AI>},
    #   {"role": "user",   "content": <json con meta, period_block, ecc.>}
    # ]
    system_prompt = ""
    user_content = ""

    for m in messages:
        role = m.get("role")
        content = m.get("content") or ""
        if role == "system":
            system_prompt = content
        elif role == "user":
            user_content = content

    client = Anthropic(api_key=api_key)

    try:
        resp = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system_prompt,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": user_content,
                        }
                    ],
                }
            ],
        )
    except APIStatusError as e:
        # Log minimale
        print("[CLAUDE ERROR]", e.status_code, e.response)
        raise HTTPException(
            status_code=502,
            detail=f"Errore chiamata Claude: HTTP {e.status_code}",
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Errore chiamata Claude: {e}")

    # Testo restituito da Claude
    text = ""
    if resp.content and len(resp.content) > 0:
        text = resp.content[0].text

    # 1° tentativo: parse diretto
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 2° tentativo: pulizia da ```json ... ```
    cleaned = text.strip()
    if cleaned.startswith("```"):
        # togli backtick iniziali/finali
        cleaned = cleaned.strip("`").strip()
        # togli "json" iniziale se presente
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:].strip()

    try:
        return json.loads(cleaned)
    except Exception:
        # se proprio non è JSON, alziamo errore leggibile
        preview = (cleaned or text)[:500]
        raise HTTPException(
            status_code=500,
            detail=f"Claude ha restituito JSON non valido: {preview}",
        )

# =========================================================
#  Chiamata Groq — JSON via response_format
# =========================================================

def _call_groq_json(messages: List[Dict[str, str]], model: str, max_tokens: int, temperature: float):
    """
    Chiamata a Groq usando l'endpoint OpenAI-compatibile.
    Ritorna SEMPRE JSON valido oppure lancia HTTPException.
    """
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="GROQ_API_KEY non configurata")

    try:
        resp = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "response_format": {"type": "json_object"},
            },
            timeout=60,
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Errore chiamata Groq: {e}")

    if resp.status_code != 200:
        raise HTTPException(
            status_code=502,
            detail=f"Groq HTTP {resp.status_code}: {resp.text[:800]}",
        )

    content = resp.json()["choices"][0]["message"]["content"]
    try:
        return json.loads(content)
    except Exception:
        raise HTTPException(
            status_code=500,
            detail=f"Groq ha restituito JSON non valido: {content[:500]}",
        )

# =========================================================
#  Costruzione dei messages (smistamento unificato)
# =========================================================

def _build_groq_messages(req: OroscopoAIRequest, payload_ai: Dict[str, Any]):
    meta = payload_ai.get("meta") or {}
    periodo = req.periodo
    tier = req.tier.lower()

    period_block = _extract_period_block(payload_ai, periodo)

    kb_md = ((payload_ai.get("kb") or {}).get("combined_markdown")) or ""
    kb_md = kb_md[:8000]  # limiti di sicurezza

    # riepiloghi già pronti
    aspetti_rilevanti = _summary_aspetti(period_block, max_n=25)

    return _build_messages_oroscopo_ai_unificato(
        meta=meta,
        periodo=periodo,
        tier=tier,
        period_block=period_block,
        kb_markdown=kb_md,
        aspetti_rilevanti=aspetti_rilevanti,
    )

@router.post("/oroscopo_ai", response_model=OroscopoAIResponse)
def oroscopo_ai(req: OroscopoAIRequest) -> OroscopoAIResponse:
    start = time.time()

    payload_ai = req.payload_ai
    period_block = _extract_period_block(payload_ai, req.periodo)

    # riepiloghi "di servizio" per la response
    intensities = _summary_intensities(period_block)
    pianeti = _summary_pianeti(period_block)
    aspetti = _summary_aspetti(period_block, max_n=20)

    # costruiamo il messaggio unificato (super-prompt + JSON user)
    messages = _build_groq_messages(req, payload_ai)

    # parametri AI dinamici
    max_tokens = 1200 if req.tier == "premium" else 800
    temperature = float(os.environ.get("AI_TEMPERATURE", "0.6"))

    interpretazione = None

    if req.tier == "premium":
        # PREMIUM → CLAUDE (miglior qualità, accetto costo)
        model = "claude-3-5-haiku-latest"
        interpretazione = _call_claude_json(
            messages=messages,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
        )
    else:
        # FREE → GROQ (più economico)
        groq_model = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
        interpretazione = _call_groq_json(
            messages=messages,
            model=groq_model,
            max_tokens=max_tokens,
            temperature=temperature,
        )

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
# =========================================================
#  FINE FILE – routes_oroscopo.py (versione finale)
# =========================================================

