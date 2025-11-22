<<<<<<< HEAD
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
    build_oroscopo_payload_ai,
    PERIOD_KEY_TO_CODE,
)




router = APIRouter()

# =========================================================
#  Pesi pianeti per periodo (rimangono IDENTICI)
# =========================================================
=======
# routes_oroscopo.py

from datetime import date, timedelta
from typing import Optional, Literal, Dict, Any, List

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

router = APIRouter(
    prefix="/oroscopo",
    tags=["oroscopo"],
)

# ==========================
# MODELLI
# ==========================
>>>>>>> 9a8b3bf3aa79f42286c8a38433954d6a49cc8a72

ScopeType = Literal["daily", "weekly", "monthly", "yearly"]

<<<<<<< HEAD
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

class OroscopoSiteRequest(BaseModel):
    """
    Richiesta semplificata che arriva dal sito DYANA.
    """
    nome: Optional[str] = None
    citta: str
    data_nascita: str        # "YYYY-MM-DD"
    ora_nascita: str         # "HH:MM"
    periodo: Literal["giornaliero", "settimanale", "mensile", "annuale"]
    tier: Literal["free", "premium", "auto"] = "auto"

# =========================================================
#  Utility comuni (rimangono identiche)
# =========================================================
=======

class OroscopoRequest(BaseModel):
    """
    Input minimale e compatibile con /tema:
    - citta: metadata
    - data: riferimento per lo scope
    """
    citta: str
    data: date
    nome: Optional[str] = None
    email: Optional[str] = None
    domanda: Optional[str] = None
    tier: Optional[str] = "free"


class OroscopoResponse(BaseModel):
    status: str
    scope: ScopeType
    engine: Literal["legacy", "new"]
    input: Dict[str, Any]
    result: Dict[str, Any]   # payload specifico dell’oroscopo


# ==========================
# UTILS
# ==========================
>>>>>>> 9a8b3bf3aa79f42286c8a38433954d6a49cc8a72


def _resolve_tier_for_site(req_tier: str) -> str:
    """
    Per ora:
    - se il frontend specifica 'free' o 'premium', usiamo quello
    - se manda 'auto' (o niente), trattiamo come 'free'
    Più avanti qui leggeremo il JWT per capire il tier reale.
    """
    value = (req_tier or "").lower()
    if value in ("free", "premium"):
        return value
    return "free"







def _blank_png_no_prefix() -> str:
    # 1x1 pixel trasparente (senza prefisso data:image)
    return "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR4nGNgYAAAAAMAASsJTYQAAAAASUVORK5CYII="

<<<<<<< HEAD

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
=======

# ==========================
# MOTORI (LEGACY + NEW)
# ==========================

def calcola_oroscopo_legacy(scope: ScopeType, payload: OroscopoRequest) -> Dict[str, Any]:
    return {
        "engine_version": "legacy",
>>>>>>> 9a8b3bf3aa79f42286c8a38433954d6a49cc8a72
        "scope": scope,
        "note": "Motore legacy non collegato: usa X-Engine: new per la pipeline nuova.",
    }


<<<<<<< HEAD
# =========================================================
#  Helpers per /oroscopo_ai
# =========================================================
=======
def _build_date_series(scope: ScopeType, base_date: date) -> List[date]:
    if scope == "daily":
        return [base_date]
    if scope == "weekly":
        return [base_date + timedelta(days=i) for i in range(7)]
    if scope == "monthly":
        start = base_date - timedelta(days=14)
        return [start + timedelta(days=i) for i in range(30)]
    if scope == "yearly":
        start = date(base_date.year, 1, 1)
        return [start + timedelta(days=30 * i) for i in range(12)]
    return [base_date]
>>>>>>> 9a8b3bf3aa79f42286c8a38433954d6a49cc8a72


<<<<<<< HEAD

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
        
# TODO: quando avrai l’auth a token, potrai sostituire questa dipendenza
# con qualcosa che ti dà il tier reale.
def _resolve_tier_from_site(req_tier: str) -> str:
    """
    Per ora:
    - se tier esplicito = "free" o "premium" → lo usiamo
    - se tier = "auto" → trattiamo come free (più avanti leggeremo il JWT)
    """
    if req_tier in ("free", "premium"):
        return req_tier
    return "free"


@router.post("/oroscopo_site", response_model=OroscopoAIResponse)
def oroscopo_site_endpoint(req: OroscopoSiteRequest) -> OroscopoAIResponse:
    """
    Endpoint "alto livello" per il sito DYANA.

    Flusso:
    1) costruisce oroscopo_struct con la pipeline multi-snapshot
    2) usa build_oroscopo_payload_ai(...) per creare il payload_ai
    3) chiama la stessa logica di /oroscopo_ai, riutilizzando prompt + Claude
    """

    # 1) Normalizziamo periodo e tier
    period_code = PERIOD_KEY_TO_CODE.get(req.periodo, "daily")  # es: "giornaliero" -> "daily"
    effective_tier = _resolve_tier_from_site(req.tier)

    # 2) Costruiamo oroscopo_struct con la tua pipeline
    # ⚠️ QUI devi usare la funzione reale che hai in astrobot-core.
    # Lascio un esempio generico con un TODO esplicito.
    #
    # Esempio (devi adattare al tuo modulo reale):
    #
    # from astrobot_core.oroscopo_engine import run_oroscopo_multi_snapshot
    #
    # oroscopo_struct = run_oroscopo_multi_snapshot(
    #     periodo=req.periodo,           # "giornaliero"/"settimanale"/...
    #     tier=effective_tier,
    #     nome=req.nome,
    #     citta=req.citta,
    #     data_nascita=req.data_nascita,
    #     ora_nascita=req.ora_nascita,
    # )

    # Placeholder temporaneo per non rompere nulla: struttura minima.
    oroscopo_struct = {
        "meta": {
            "nome": req.nome,
            "citta": req.citta,
            "data_nascita": req.data_nascita,
            "ora_nascita": req.ora_nascita,
            "tier": effective_tier,
            "periodo": req.periodo,
            "lang": "it",
        },
        "periodo": req.periodo,
        "periodi": {},          # la pipeline reale popolerà questa sezione
        "tema": {},
        "profilo_natale": {},
        "kb_hooks": {},
    }

    # 3) Costruiamo il payload_ai con il modulo che mi hai passato
    payload_ai = build_oroscopo_payload_ai(
        oroscopo_struct=oroscopo_struct,
        lang="it",
        period_code=period_code,
    )

    # 4) Prepariamo una OroscopoAIRequest e riutilizziamo la logica di /oroscopo_ai
    ai_req = OroscopoAIRequest(
        scope="oroscopo_ai",
        tier=effective_tier,
        periodo=req.periodo,
        payload_ai=payload_ai,
    )

    ai_resp = oroscopo_ai(ai_req)
    return ai_resp       
        

=======
def _build_intensities_for_dates(dates: List[date]) -> Dict[str, List[float]]:
    import math
    n = len(dates)
    if n == 0:
        return {k: [] for k in ["energy","emotions","relationships","work","luck"]}
    base_ord = dates[0].toordinal()

    def norm_sin(idx: int, freq: float, phase: float = 0.0, amp: float = 0.40, bias: float = 0.5) -> float:
        x = idx / max(n - 1, 1)
        val = math.sin(2 * math.pi * (freq * x + phase + base_ord * 0.01))
        out = bias + amp * val
        return 0.0 if out < 0.0 else 1.0 if out > 1.0 else out

    energy        = [norm_sin(i, freq=0.9, phase=0.1) for i in range(n)]
    emotions      = [norm_sin(i, freq=0.7, phase=0.35) for i in range(n)]
    relationships = [norm_sin(i, freq=0.8, phase=0.55) for i in range(n)]
    work          = [norm_sin(i, freq=1.1, phase=0.2, amp=0.45) for i in range(n)]
    luck          = [norm_sin(i, freq=0.5, phase=0.8, amp=0.35, bias=0.55) for i in range(n)]

    return {
        "energy": energy,
        "emotions": emotions,
        "relationships": relationships,
        "work": work,
        "luck": luck,
    }


def _build_label_map_it() -> Dict[str, str]:
    return {
        "energy": "Energia",
        "emotions": "Emozioni",
        "relationships": "Relazioni",
        "work": "Lavoro",
        "luck": "Fortuna",
    }


def calcola_oroscopo_new(scope: ScopeType, payload: OroscopoRequest) -> Dict[str, Any]:
    """
    Motore NEW:
    - genera date + intensità 0–1 (5 domini)
    - prova a renderizzare il grafico a linee premium dal core
      con fallback a PNG trasparente se il modulo non è disponibile.
    """
    # 1) serie di date
    date_list = _build_date_series(scope, payload.data)
    date_strings = [d.isoformat() for d in date_list]

    # 2) intensità sintetiche
    intensities = _build_intensities_for_dates(date_list)

    # 3) grafico (import lazy + fallback)
    label_map = _build_label_map_it()
    png_base64 = None
    try:
        from astrobot_core.grafici import grafico_linee_premium  # <-- import lazy
        png_base64 = grafico_linee_premium(
            date_strings=date_strings,
            intensities_series=intensities,
            scope=scope,
            label_map=label_map,
        )
    except Exception:
        png_base64 = _blank_png_no_prefix()
>>>>>>> 9a8b3bf3aa79f42286c8a38433954d6a49cc8a72

    if png_base64 and not png_base64.startswith("data:image/png;base64,"):
        png_base64_with_prefix = "data:image/png;base64," + png_base64
    else:
        png_base64_with_prefix = png_base64

    return {
        "engine_version": "new",
        "scope": scope,
        "meta": {
            "citta": payload.citta,
            "nome": payload.nome,
            "email": payload.email,
            "domanda": payload.domanda,
        },
        "dates": date_strings,
        "intensities": intensities,
        "grafico_linee_png": png_base64_with_prefix,
    }


# ==========================
# ROUTE UNICA /oroscopo/{scope}
# ==========================

@router.post("/{scope}", response_model=OroscopoResponse)
async def oroscopo_endpoint(
    scope: ScopeType,
    payload: OroscopoRequest,
    x_engine: Optional[str] = Header(default=None, alias="X-Engine"),
):
    """
    POST /oroscopo/{daily|weekly|monthly|yearly}
    - se X-Engine: new → usa il motore nuovo
    - altrimenti → motore legacy (backward compatibility)
    """
    engine_flag = (x_engine or "").lower().strip()
    if engine_flag not in ("", "new"):
        raise HTTPException(status_code=400, detail="Valore X-Engine non valido. Usa 'new' oppure ometti l'header.")

    use_new_engine = engine_flag == "new"
    result = calcola_oroscopo_new(scope, payload) if use_new_engine else calcola_oroscopo_legacy(scope, payload)
    engine_name = "new" if use_new_engine else "legacy"

    return OroscopoResponse(
        status="ok",
        scope=scope,
        engine=engine_name,
        input=payload.model_dump(),
        result=result,
    )
# =========================================================
#  FINE FILE – routes_oroscopo.py (versione finale)
# =========================================================

@router.post("/oroscopo_site")
def oroscopo_site(req: OroscopoSiteRequest) -> dict:
    """
    Endpoint *semplice* pensato per il sito DYANA.

    In questo step è solo uno STUB:
    - non usa ancora la pipeline vera,
    - non chiama ancora build_oroscopo_payload_ai,
    - non chiama ancora Claude.

    Serve solo per:
    - verificare che la route funzioni,
    - definire la struttura base della risposta,
    - prepararci a collegare, passo dopo passo, la pipeline reale.
    """
    effective_tier = _resolve_tier_for_site(req.tier)

    # Qui per ora facciamo SOLO eco dei dati ricevuti,
    # con un messaggio "TODO" ben chiaro.
    return {
        "status": "ok",
        "scope": req.periodo,
        "engine": "site_stub",
        "tier": effective_tier,
        "input": {
            "nome": req.nome,
            "citta": req.citta,
            "data_nascita": req.data_nascita,
            "ora_nascita": req.ora_nascita,
            "periodo": req.periodo,
            "tier": req.tier,
        },
        "result": {
            "meta": {
                "msg": "Stub oroscopo_site: la pipeline AI non è ancora collegata.",
                "nota": "Prossimo step: usare run_oroscopo_multi_snapshot + build_oroscopo_struct_from_pipe + build_oroscopo_payload_ai.",
            }
        },
    }
