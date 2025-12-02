"""
oroscopo_payload_ai.py

Costruisce il payload AI per l'oroscopo, integrando:

- meta (dati utente / contesto)
- periodi (giornaliero, settimanale, mensile, annuale)
- kb_hooks (ganci verso la Knowledge Base)
- kb (contenuto markdown estratto da Supabase)

Gestione volume KB su 2 livelli:
1) NUMERO DI VOCI (entry KB) → dipende da tier/periodo
2) VOLUME DI TESTO (caratteri markdown) → limite per tier

⚠️ NOTA ARCHITETTURALE:
- Questo modulo NON calcola la logica dei periodi (es. decadi del mensile),
  ma accetta una struttura `oroscopo_struct` prodotta dalla pipeline:

    run_oroscopo_multi_snapshot(periodo=..., tier=...)

  che attualmente restituisce, per UN singolo periodo:

    {
        "anchor_date": ...,
        "snapshots_info": ...,
        "metriche_grafico": ...,
        "aspetti_rilevanti": ...,
        "snapshots_raw": ...,
        "profilo_natale": ...,
        "tema_natale": ...,
        "pianeti_prevalenti": ...
    }

- Qui ci limitiamo a:
  - normalizzare tier/period_code
  - costruire la sezione `periodi` nel formato atteso dal backend /oroscopo_ai
  - risolvere i kb_hooks e applicare i limiti KB.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Set, Tuple

from .fetch_kb_from_hooks import fetch_kb_from_hooks
import json
# =========================================================
#  Mappa periodi e policy limiti KB
# =========================================================
from typing import Dict, Tuple, Any

# ============================
# Mappa periodi IT <-> codici
# ============================

# Mappa chiavi italiane dei periodi -> codici interni
PERIOD_KEY_TO_CODE: Dict[str, str] = {
    "giornaliero": "daily",
    "settimanale": "weekly",
    "mensile": "monthly",
    "annuale": "yearly",
}

# Mappa inversa: codici interni -> chiavi italiane
CODE_TO_PERIOD_KEY: Dict[str, str] = {v: k for k, v in PERIOD_KEY_TO_CODE.items()}

# ============================
# Limiti entità per AI (LIGHT)
# ============================

# Chiave: (periodo IT, tier)
# periodo IT ∈ { "giornaliero", "settimanale", "mensile", "annuale" }
# tier ∈ { "free", "premium" }
#
# Ogni entry contiene:
# - max_aspetti: quanti aspetti_chiave passare al modello
# - max_pianeti_prevalenti: quanti pianeti prevalenti usare nel contesto
# - max_kb_chars: quanti caratteri tenere da kb.markdown per quel periodo/tier
AI_ENTITY_LIMITS: Dict[Tuple[str, str], Dict[str, Any]] = {
    ("giornaliero", "free"): {
        "max_aspetti": 3,
        "max_pianeti_prevalenti": 1,
        "max_kb_chars": 200,
    },
    ("giornaliero", "premium"): {
        "max_aspetti": 5,
        "max_pianeti_prevalenti": 2,
        "max_kb_chars": 400,
    },
    ("settimanale", "free"): {
        "max_aspetti": 3,
        "max_pianeti_prevalenti": 2,
        "max_kb_chars": 350,
    },
    ("settimanale", "premium"): {
        "max_aspetti": 6,
        "max_pianeti_prevalenti": 3,
        "max_kb_chars": 600,
    },
    ("mensile", "free"): {
        "max_aspetti": 4,
        "max_pianeti_prevalenti": 3,
        "max_kb_chars": 600,
    },
    ("mensile", "premium"): {
        "max_aspetti": 8,
        "max_pianeti_prevalenti": 4,
        "max_kb_chars": 1200,
    },
    ("annuale", "free"): {
        "max_aspetti": 3,
        "max_pianeti_prevalenti": 2,
        "max_kb_chars": 400,
    },
    ("annuale", "premium"): {
        "max_aspetti": 8,
        "max_pianeti_prevalenti": 4,
        "max_kb_chars": 1500,
    },
}

# ============================
# Default
# ============================

DEFAULT_TIER = "free"
DEFAULT_PERIOD_CODE = "daily"
DEFAULT_PERIOD_KEY = "giornaliero"

# =========================================================
#  Funzione principale: build_oroscopo_payload_ai
# =========================================================

def build_oroscopo_payload_ai(
    oroscopo_struct: Dict[str, Any],
    lang: str = "it",
    period_code: str = "daily",
) -> Dict[str, Any]:
    """
    Costruisce il payload finale da mandare al backend AI (Claude/Groq).

    NOTE IMPORTANTI:
    - Riduciamo *esplicitamente* la lunghezza di kb.combined_markdown
      usando AI_ENTITY_LIMITS[(periodo_it, tier)]["max_kb_chars"].
    - NON inviamo più strutture pesanti (liste di pianeti_prevalenti /
      aspetti_rilevanti) nel campo "kb": per l'AI basta il markdown.
    """

    # ---------------------------------------------------------
    # 1) META + TIER NORMALIZZATO
    # ---------------------------------------------------------
    raw_meta = oroscopo_struct.get("meta") or {}
    raw_tier = raw_meta.get("tier") or oroscopo_struct.get("tier")
    tier = _normalize_tier(raw_tier)

    # ricostruiamo meta garantendo lang + tier
    meta: Dict[str, Any] = dict(raw_meta) if raw_meta else {}
    meta["lang"] = lang
    meta["tier"] = tier

    # ---------------------------------------------------------
    # 2) PERIODO PRINCIPALE (daily/weekly/mensile/annuale)
    # ---------------------------------------------------------
    # se period_code è passato dal chiamante lo usiamo, altrimenti
    # proviamo a inferirlo dallo struct (campo "periodo" o chiavi di "periodi")
    effective_period_code = period_code or _infer_primary_period_code(oroscopo_struct)
    period_key_it = CODE_TO_PERIOD_KEY.get(effective_period_code, DEFAULT_PERIOD_KEY)

    # ---------------------------------------------------------
    # 3) ESTRAZIONE PARTI NUCLEARI DALLO STRUCT
    # ---------------------------------------------------------
    tema = oroscopo_struct.get("tema") or {}
    profilo_natale = oroscopo_struct.get("profilo_natale") or {}
    raw_periodi = oroscopo_struct.get("periodi") or {}
    kb_hooks = oroscopo_struct.get("kb_hooks") or {}

    # Normalizziamo i nomi dei periodi in italiano (giornaliero, settimanale, …)
    periodi = _build_periodi_payload(raw_periodi, effective_period_code)

    # ---------------------------------------------------------
    # 4) KB HOOKS + APPLICAZIONE LIMITI PER PERIODO/TIER
    # ---------------------------------------------------------
    kb_combined_raw: str = kb_hooks.get("combined_markdown") or ""

    # (NON usiamo più kb_pianeti_prev / kb_aspetti_rel nel payload AI,
    #  restano comunque disponibili in oroscopo_struct["kb_hooks"] se servono altrove)
    # kb_pianeti_prev = kb_hooks.get("pianeti_prevalenti") or []
    # kb_aspetti_rel = kb_hooks.get("aspetti_rilevanti") or []

    # Recupero del config di limiti per (periodo_it, tier)
    limits_cfg = (
        AI_ENTITY_LIMITS.get((period_key_it, tier))
        or AI_ENTITY_LIMITS.get((DEFAULT_PERIOD_KEY, DEFAULT_TIER))
    )
    max_kb_chars: Optional[int] = limits_cfg.get("max_kb_chars") if limits_cfg else None

    # Taglio effettivo del markdown KB in base ai limiti
    kb_combined = _clip_markdown(kb_combined_raw, max_kb_chars)

    # ---------------------------------------------------------
    # 5) COSTRUZIONE PAYLOAD FINALE (KB LIGHT)
    # ---------------------------------------------------------
    # Nel campo "kb" inviamo solo il markdown già sintetico.
    kb_block: Dict[str, Any] = {
        "combined_markdown": kb_combined
    }

    payload_ai: Dict[str, Any] = {
        "meta": meta,
        "tema": tema,
        "profilo_natale": profilo_natale,
        "periodi": periodi,
        "kb": kb_block,
        "engine": "astrobot-core",
        "period_code": effective_period_code,
    }

    # ---------------------------------------------------------
    # 6) DEBUG: VERIFICA DIMENSIONI KB DOPO IL TAGLIO
    # ---------------------------------------------------------
    print(
        f"\n[DEBUG PAYLOAD_AI] CONTEXT: tier={tier}, "
        f"period_code={effective_period_code}, period_key_it={period_key_it}"
    )
    print(f"[DEBUG PAYLOAD_AI] LIMITS CFG: {limits_cfg}")

    print("\n[DEBUG PAYLOAD_AI] KEYS:", list(payload_ai.keys()))
    kb_len = len(kb_combined)
    print(f"[DEBUG PAYLOAD_AI] kb.combined_markdown length = {kb_len}")
    if kb_len > 0:
        print("[DEBUG PAYLOAD_AI] kb.combined_markdown (primi 300 char):")
        print(kb_combined[:300])
    else:
        print("[DEBUG PAYLOAD_AI] ATTENZIONE: kb.combined_markdown vuoto!")

    # Debug extra: per vedere cosa c'è dentro kb
    print("[DEBUG PAYLOAD_AI] KB KEYS:", list(kb_block.keys()))

    # Stima dimensione totale del payload (per monitorare il "dimagrimento")
    try:
        import json
        payload_size = len(json.dumps(payload_ai, ensure_ascii=False))
        print(f"[DEBUG PAYLOAD_AI] dimensione totale payload_ai (char) = {payload_size}")
    except Exception:
        pass

    return payload_ai


# =========================================================
#  Helper vari
# =========================================================

def _normalize_tier(raw_tier: Any) -> str:
    """Normalizza il tier in {free, premium}."""
    if not raw_tier:
        return DEFAULT_TIER
    s = str(raw_tier).strip().lower()
    if s in {"premium", "paid", "pro"}:
        return "premium"
    return "free"


def _infer_primary_period_code(oroscopo_struct: Dict[str, Any]) -> str:
    """
    Determina il periodo principale da oroscopo_struct.
    Per la pipeline single-period, al limite ritorna 'daily'.
    """
    # Se esiste un campo "periodo" in italiano
    periodo_it = str(oroscopo_struct.get("periodo", "")).strip().lower()
    if periodo_it in PERIOD_KEY_TO_CODE:
        return PERIOD_KEY_TO_CODE[periodo_it]

    # Se esiste una chiave "periodi" con dentro un solo periodo
    periodi = oroscopo_struct.get("periodi") or {}
    if isinstance(periodi, dict) and len(periodi) == 1:
        k = list(periodi.keys())[0]
        if k in PERIOD_KEY_TO_CODE:
            return PERIOD_KEY_TO_CODE[k]
        if k in {"daily", "weekly", "monthly", "yearly"}:
            return k

    return DEFAULT_PERIOD_CODE


def _get_kb_limits_for_context(tier: str, period_code: str) -> Dict[str, Any]:
    """Restituisce i limiti KB per (tier, periodo)."""
    tier_cfg = KB_LIMITS_POLICY.get(tier) or KB_LIMITS_POLICY[DEFAULT_TIER]
    period_cfg = tier_cfg.get(period_code) or tier_cfg.get(DEFAULT_PERIOD_CODE)

    per_section = period_cfg.get("per_section", {})
    max_total_entries = period_cfg.get("max_total_entries")
    max_kb_chars = KB_CHAR_LIMIT_BY_TIER.get(tier, KB_CHAR_LIMIT_BY_TIER[DEFAULT_TIER])

    return {
        "max_entries_per_section": per_section,
        "max_total_entries": max_total_entries,
        "max_kb_chars": max_kb_chars,
    }


def _build_meta(raw_meta: Dict[str, Any], lang: str, tier: str) -> Dict[str, Any]:
    meta = dict(raw_meta) if raw_meta else {}
    meta["lang"] = lang
    meta["tier"] = tier
    return meta


def _clip_markdown(text: str, max_chars: Optional[int]) -> str:
    """Tronca il markdown se eccede i limiti."""
    if not text:
        return ""
    if not max_chars or max_chars <= 0:
        return text
    if len(text) <= max_chars:
        return text

    note = (
        "\n\n---\n\n"
        "[KB TRONCATA PER LIMITI DI CONTESTO: la Knowledge Base completa è disponibile "
        "ma questa è una selezione automatica delle parti più rilevanti in base ai kb_hooks.]\n"
    )
    return text[:max_chars] + note


# =========================================================
#  Costruzione PERIODI per il payload AI
# =========================================================

def _build_periodi_payload(
    raw_periodi: Dict[str, Any],
    primary_period_code: str,
) -> Dict[str, Any]:
    """
    Prepara la sezione 'periodi' del payload AI a partire da raw_periodi.

    Gestisce sia chiavi inglesi (daily/weekly/...) sia italiane (giornaliero/...),
    ma il backend /oroscopo_ai si aspetta SEMPRE chiavi italiane:

    - giornaliero
    - settimanale
    - mensile
    - annuale
    """
    if not isinstance(raw_periodi, dict):
        return {}

    periodi: Dict[str, Any] = {}
    for key, value in raw_periodi.items():
        period_key_it = CODE_TO_PERIOD_KEY.get(key, key)
        periodi[period_key_it] = value

    return periodi


# =========================================================
#  KB hooks
# =========================================================

def _build_kb_hooks(oroscopo_struct: Dict[str, Any], period_code: str) -> Dict[str, Any]:
    """
    Costruisce i kb_hooks a partire da:

    - tema natale (pianeti, segni, case)
    - transiti (se presenti in oroscopo_struct["transiti"])
    """

    pianeti: Set[str] = set()
    segni: Set[str] = set()
    case: Set[int] = set()
    pianeti_case: Set[Tuple[str, int]] = set()
    transiti_pianeti: Set[Tuple[str, str, str]] = set()

    # ---------- Tema natale: pianeti e segni ----------
    tema = oroscopo_struct.get("tema") or oroscopo_struct.get("tema_natale") or {}
    pianeti_decod = tema.get("pianeti_decod") or {}
    for nome_pianeta, dati in pianeti_decod.items():
        if not isinstance(dati, dict):
            continue
        nome_lower = str(nome_pianeta).lower()
        if nome_lower in {"data", "asc", "ascendente", "mc", "medium_coeli", "discendente", "cuspidi"}:
            continue
        pianeti.add(str(nome_pianeta))
        segno = dati.get("segno") or dati.get("sign")
        if segno:
            segni.add(str(segno))

    case_decod = tema.get("case_decod") or {}
    if isinstance(case_decod, dict):
        for k, dati_casa in case_decod.items():
            try:
                n_casa = int(k)
            except (TypeError, ValueError):
                continue
            case.add(n_casa)
            if isinstance(dati_casa, dict):
                segno_casa = dati_casa.get("segno") or dati_casa.get("sign")
                if segno_casa:
                    segni.add(str(segno_casa))

    # ---------- TRANSITI: se presenti in oroscopo_struct["transiti"] ----------
    all_transits = oroscopo_struct.get("transiti") or []
    filtered: List[Dict[str, Any]] = []
    if isinstance(all_transits, list):
        for tr in all_transits:
            if not isinstance(tr, dict):
                continue
            code = tr.get("period_code")
            if code is not None and code != period_code:
                continue
            filtered.append(tr)

    if filtered:
        transits = filtered
    else:
        transits = all_transits if isinstance(all_transits, list) else []

    for tr in transits:
        if not isinstance(tr, dict):
            continue

        tp = tr.get("transit_planet")
        np = tr.get("natal_planet")
        asp = tr.get("aspect")

        # 🚫 Escludiamo il quincunce dagli hook KB (non abbiamo testi per questo aspetto)
        if asp in {"quincunce", "quincunx"}:
            continue

        if tp and np and asp:
            transiti_pianeti.add((str(tp), str(np), str(asp)))
            pianeti.add(str(tp))
            segno_tr = tr.get("segno") or tr.get("sign")
            if segno_tr:
                segni.add(str(segno_tr))


    hooks: Dict[str, Any] = {}
    if case:
        hooks["case"] = sorted(case)
    if pianeti:
        hooks["pianeti"] = sorted(pianeti)
    if segni:
        hooks["segni"] = sorted(segni)
    if pianeti_case:
        hooks["pianeti_case"] = [
            {"transit_planet": tp, "natal_house": h}
            for tp, h in sorted(pianeti_case)
        ]
    if transiti_pianeti:
        hooks["transiti_pianeti"] = [
            {"transit_planet": tp, "natal_planet": np, "aspect": asp}
            for tp, np, asp in sorted(transiti_pianeti)
        ]

    return hooks
