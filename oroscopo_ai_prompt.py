"""
oroscopo_ai_prompt.py

Costruisce i messaggi (system + user) per la chiamata a Groq,
a partire dal payload_ai che arriva dal backend AstroBot.

Supporta:
- periodi generici (daily/weekly/yearly): schema classico
  {sintesi, amore, lavoro, crescita_personale, consigli_pratici}

- periodo mensile (monthly): schema arricchito con:
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
        "consigli_pratici": [...]
      },
      ...
    ]
  }
"""

from __future__ import annotations

import json
from typing import Any, Dict, List


def build_groq_messages(payload_wrapper: Dict[str, Any]) -> List[Dict[str, str]]:
    """
    payload_wrapper: dict come quello che riceve il backend via /oroscopo_ai, es:

    {
      "scope": "oroscopo_ai",
      "tier": "premium",
      "periodo": "mensile",
      "payload_ai": {
        "meta": {...},
        "tier": "premium",
        "period_code": "monthly",
        "periodi": {
          "mensile": {
            "label": "...",
            "date_range": {...},
            "intensita_mensile": {...},
            "sottoperiodi": [
              {
                "id": "inizio_mese",
                "label": "...",
                "date_range": {...},
                "intensita": {...},
                "pianeti_prevalenti": [...],
                "aspetti_rilevanti": [...]
              },
              ...
            ]
          },
          ...
        },
        "kb": {
          "combined_markdown": "...",
          ...
        }
      }
    }
    """
    tier = str(payload_wrapper.get("tier") or payload_wrapper.get("payload_ai", {}).get("tier") or "free").lower()
    if tier not in {"free", "premium"}:
        tier = "free"

    periodo_human = str(payload_wrapper.get("periodo") or "").lower()
    payload_ai = payload_wrapper.get("payload_ai") or {}
    period_code = payload_ai.get("period_code") or _map_periodo_to_code(periodo_human)

    meta = payload_ai.get("meta") or {}
    periodi = payload_ai.get("periodi") or {}
    kb = payload_ai.get("kb") or {}
    kb_markdown = kb.get("combined_markdown", "")

    if period_code == "monthly":
        return _build_messages_mensile(
            tier=tier,
            meta=meta,
            periodi=periodi,
            kb_markdown=kb_markdown,
        )
    else:
        return _build_messages_generico(
            tier=tier,
            meta=meta,
            periodi=periodi,
            period_code=period_code,
            kb_markdown=kb_markdown,
        )


# ---------------------------------------------------------------------------
#  Mappers & helper
# ---------------------------------------------------------------------------

def _map_periodo_to_code(periodo: str) -> str:
    periodo = (periodo or "").lower()
    if periodo == "giornaliero":
        return "daily"
    if periodo == "settimanale":
        return "weekly"
    if periodo == "mensile":
        return "monthly"
    if periodo == "annuale":
        return "yearly"
    return "daily"


# ---------------------------------------------------------------------------
#  Prompt GENERICO (daily/weekly/yearly) – schema "classico"
# ---------------------------------------------------------------------------

def _build_messages_generico(
    tier: str,
    meta: Dict[str, Any],
    periodi: Dict[str, Any],
    period_code: str,
    kb_markdown: str,
) -> List[Dict[str, str]]:
    """
    Mantiene lo schema classico:

    {
      "sintesi": "...",
      "amore": "...",
      "lavoro": "...",
      "crescita_personale": "...",
      "consigli_pratici": ["...", "..."]
    }
    """
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

    # Per il generico prendiamo il primo periodo disponibile come contesto
    periodo_key = None
    for k in ("giornaliero", "settimanale", "annuale", "mensile"):
        if k in periodi:
            periodo_key = k
            break
    if not periodo_key and periodi:
        periodo_key = list(periodi.keys())[0]

    periodo_data = periodi.get(periodo_key, {}) if periodo_key else {}

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
            "key": periodo_key,
            "label": periodo_data.get("label"),
            "date_range": periodo_data.get("date_range"),
            "intensita": periodo_data.get("intensita", {}),
            "pianeti_prevalenti": periodo_data.get("pianeti_prevalenti", []),
            "aspetti_rilevanti": periodo_data.get("aspetti_rilevanti", []),
        },
        "kb_markdown": kb_markdown,
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


# ---------------------------------------------------------------------------
#  Prompt MENSILE con 4 sottoperiodi (capitoli)
# ---------------------------------------------------------------------------

def _build_messages_mensile(
    tier: str,
    meta: Dict[str, Any],
    periodi: Dict[str, Any],
    kb_markdown: str,
) -> List[Dict[str, str]]:
    """
    Caso specifico: PERIODO MENSILE con sottoperiodi.

    Schema di OUTPUT richiesto:

    {
      "sintesi_mensile": "stringa con visione generale del mese",
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
        {
          "id": "meta_mese",
          "titolo": "Metà mese (11–20)",
          ...
        },
        {
          "id": "fine_mese",
          "titolo": "Fine mese (21–fine mese)",
          ...
        },
        {
          "id": "inizio_mese_successivo",
          "titolo": "Inizio mese successivo",
          ...
        }
      ]
    }
    """
    mensile = periodi.get("mensile") or {}
    sottoperiodi = mensile.get("sottoperiodi") or []
    intensita_mensile = mensile.get("intensita_mensile", {})
    date_range = mensile.get("date_range")

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

    # Prepara un contesto JSON leggibile dal modello
    sottoperiodi_slim = []
    for sp in sottoperiodi:
        sottoperiodi_slim.append(
            {
                "id": sp.get("id"),
                "label": sp.get("label"),
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
            "label": mensile.get("label"),
            "date_range": date_range,
            "intensita_mensile": intensita_mensile,
            "sottoperiodi": sottoperiodi_slim,
        },
        "kb_markdown": kb_markdown,
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
