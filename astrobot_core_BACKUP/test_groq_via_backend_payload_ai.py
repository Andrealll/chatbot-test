"""
Test end-to-end AstroBot:
tema → pipeline oroscopo → oroscopo_struct → payload_ai → backend /oroscopo_ai → AI.

Periodi testati:
- giornaliero free/premium
- settimanale free/premium
- mensile free/premium
- annuale free/premium

Utente di test:
Mario, Napoli, 1986-07-19 08:50
"""

import json
import re
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

import requests

from astrobot_core.oroscopo_pipeline import run_oroscopo_multi_snapshot
from astrobot_core.oroscopo_payload_ai import build_oroscopo_payload_ai

# =========================================================
# CONFIG
# =========================================================

BASE_URL = "http://127.0.0.1:8000"
ENDPOINT = f"{BASE_URL}/oroscopo_ai"
TODAY = date.today()


# =========================================================
# CASI DI TEST
# =========================================================

@dataclass
class Persona:
    nome: str
    citta: str
    data: str
    ora: str
    periodo: str   # "giornaliero" | "settimanale" | "mensile" | "annuale"
    tier: str      # "free" | "premium"


PERSONE_TEST: List[Persona] = [
    Persona("Mario", "Napoli", "1986-07-19", "08:50", "giornaliero", "free"),
    Persona("Mario", "Napoli", "1986-07-19", "08:50", "giornaliero", "premium"),
    Persona("Mario", "Napoli", "1986-07-19", "08:50", "settimanale", "free"),
    Persona("Mario", "Napoli", "1986-07-19", "08:50", "settimanale", "premium"),
    Persona("Mario", "Napoli", "1986-07-19", "08:50", "mensile", "free"),
    Persona("Mario", "Napoli", "1986-07-19", "08:50", "mensile", "premium"),
    Persona("Mario", "Napoli", "1986-07-19", "08:50", "annuale", "free"),
    Persona("Mario", "Napoli", "1986-07-19", "08:50", "annuale", "premium"),
]


# =========================================================
# UTILITY
# =========================================================

def _safe_iso_to_dt(s: Optional[str]) -> datetime:
    if not s:
        return datetime.combine(TODAY, datetime.min.time())
    try:
        return datetime.fromisoformat(s)
    except Exception:
        return datetime.combine(TODAY, datetime.min.time())


def generate_subperiods(periodo: str, tier: str, date_range: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Genera sottoperiodi in base alla matrice definita:

    - giornaliero free: nessun sottoperiodo
    - giornaliero premium: mattina, pomeriggio, domani
    - settimanale free: settimana, weekend
    - settimanale premium: inizio settimana, metà settimana, weekend
    - mensile free: nessun sottoperiodo
    - mensile premium: 3 decadi
    - annuale free: nessun sottoperiodo
    - annuale premium: 4 stagioni
    """
    periodo = periodo.lower()
    tier = tier.lower()
    out: List[Dict[str, Any]] = []

    # Normalizziamo date_range
    start_dt = _safe_iso_to_dt(date_range.get("start"))
    end_dt = _safe_iso_to_dt(date_range.get("end"))

    # ---------------- GIORNALIERO ----------------
    if periodo.startswith("giorn"):
        if tier == "premium":
            domani = start_dt + timedelta(days=1)
            out = [
                {"id": "mattina", "label": "Mattina", "datetime": start_dt.replace(hour=9).isoformat()},
                {"id": "pomeriggio", "label": "Pomeriggio", "datetime": start_dt.replace(hour=15).isoformat()},
                {"id": "domani", "label": "Domani", "datetime": domani.isoformat()},
            ]
        return out

    # ---------------- SETTIMANALE ----------------
    if periodo.startswith("settim"):
        weekend_start = start_dt + timedelta(days=5)

        if tier == "premium":
            out = [
                {
                    "id": "inizio_settimana",
                    "label": "Inizio settimana",
                    "range": {
                        "start": start_dt.isoformat(),
                        "end": (start_dt + timedelta(days=2)).isoformat(),
                    },
                },
                {
                    "id": "meta_settimana",
                    "label": "Metà settimana",
                    "range": {
                        "start": (start_dt + timedelta(days=3)).isoformat(),
                        "end": (start_dt + timedelta(days=4)).isoformat(),
                    },
                },
                {
                    "id": "weekend",
                    "label": "Weekend",
                    "range": {
                        "start": weekend_start.isoformat(),
                        "end": (weekend_start + timedelta(days=1)).isoformat(),
                    },
                },
            ]
        else:
            out = [
                {
                    "id": "settimana",
                    "label": "Settimana intera",
                    "range": {
                        "start": start_dt.isoformat(),
                        "end": weekend_start.isoformat(),
                    },
                },
                {
                    "id": "weekend",
                    "label": "Weekend",
                    "range": {
                        "start": weekend_start.isoformat(),
                        "end": (weekend_start + timedelta(days=1)).isoformat(),
                    },
                },
            ]
        return out

    # ---------------- MENSILE ----------------
    if periodo.startswith("mens"):
        if tier == "premium":
            out = [
                {
                    "id": "prima_decade",
                    "label": "1–10 del mese",
                    "range": {
                        "start": start_dt.isoformat(),
                        "end": (start_dt + timedelta(days=9)).isoformat(),
                    },
                },
                {
                    "id": "seconda_decade",
                    "label": "11–20 del mese",
                    "range": {
                        "start": (start_dt + timedelta(days=10)).isoformat(),
                        "end": (start_dt + timedelta(days=19)).isoformat(),
                    },
                },
                {
                    "id": "terza_decade",
                    "label": "21–fine mese",
                    "range": {
                        "start": (start_dt + timedelta(days=20)).isoformat(),
                        "end": end_dt.isoformat(),
                    },
                },
            ]
        return out

    # ---------------- ANNUALE ----------------
    if periodo.startswith("ann"):
        if tier == "premium":
            year = start_dt.year if date_range.get("start") else TODAY.year
            out = [
                {"id": "inverno",   "label": "Inverno",   "range": {"start": f"{year}-01-01", "end": f"{year}-03-20"}},
                {"id": "primavera", "label": "Primavera", "range": {"start": f"{year}-03-21", "end": f"{year}-06-20"}},
                {"id": "estate",    "label": "Estate",    "range": {"start": f"{year}-06-21", "end": f"{year}-09-22"}},
                {"id": "autunno",   "label": "Autunno",   "range": {"start": f"{year}-09-23", "end": f"{year}-12-31"}},
            ]
        return out

    return out


def _rough_metrics_from_raw(raw: str, periodo: str) -> Dict[str, Any]:
    if not isinstance(raw, str):
        return {"sintesi_wc": 0, "n_capitoli": 0}

    periodo = periodo.lower()
    if periodo.startswith("giorn"):
        sintesi_key = "sintesi_giornaliera"
    elif periodo.startswith("settim"):
        sintesi_key = "sintesi_settimanale"
    elif periodo.startswith("mens"):
        sintesi_key = "sintesi_mensile"
    elif periodo.startswith("ann"):
        sintesi_key = "sintesi_annuale"
    else:
        sintesi_key = "sintesi"

    wc = 0
    m = re.search(rf'"{sintesi_key}"\s*:\s*"([^"]*)"', raw, re.S)
    if m:
        wc = len(m.group(1).split())

    n_caps = len(re.findall(r'"titolo"\s*:', raw))

    return {"sintesi_wc": wc, "n_capitoli": n_caps}


def analyze_response(persona: Persona, resp: Dict[str, Any]) -> None:
    if not resp or resp.get("status") != "ok":
        print("Risposta non OK:", resp)
        return

    interp = resp.get("interpretazione_ai") or {}
    periodo = persona.periodo.lower()

    if periodo.startswith("giorn"):
        sintesi_key = "sintesi_giornaliera"
    elif periodo.startswith("settim"):
        sintesi_key = "sintesi_settimanale"
    elif periodo.startswith("mens"):
        sintesi_key = "sintesi_mensile"
    elif periodo.startswith("ann"):
        sintesi_key = "sintesi_annuale"
    else:
        sintesi_key = "sintesi"

    if isinstance(interp, dict) and sintesi_key in interp:
        print("\n---- interpretazione_ai (JSON) ----")
        print(json.dumps(interp, ensure_ascii=False)[:2000])
        print(f"\nPAROLE SINTESI: {len(interp.get(sintesi_key, '').split())}")
        print(f"CAPITOLI: {len(interp.get('capitoli', []))}")
        return

    if isinstance(interp, dict) and "raw" in interp:
        raw = interp["raw"]
        print("\n---- interpretazione_ai (RAW) ----")
        print(raw[:2000])
        metrics = _rough_metrics_from_raw(raw, persona.periodo)
        print("\n[METRICHE GREZZE]")
        print(metrics)
        return

    print("\ninterpretazione_ai non riconosciuto:")
    print(str(interp)[:500])


# =========================================================
# TROVA IL BLOCCO PERIODO DENTRO pipe (robusto)
# =========================================================

def _pick_period_block(pipe: Dict[str, Any], persona: Persona) -> Dict[str, Any]:
    """
    Cerca il blocco periodo giusto dentro la struttura restituita da run_oroscopo_multi_snapshot.
    Lavora a tentativi in questo ordine:

    1. pipe["periodo_output"] (vecchio stile)
    2. pipe["periodi"][chiave] o pipe["periodi_multi"][chiave]
       dove chiave ∈ {persona.periodo, period_code (daily/weekly/...)}
    3. ricerca ricorsiva di un dict che contenga chiavi tipiche:
       "date_range", "aspetti_rilevanti", "metriche_grafico"
    """

    # 1) Vecchio stile
    po = pipe.get("periodo_output")
    if isinstance(po, dict) and ("date_range" in po or "aspetti_rilevanti" in po):
        return po

    # 2) Struttura periodi / periodi_multi
    periodi = pipe.get("periodi") or pipe.get("periodi_multi")
    if isinstance(periodi, dict) and periodi:
        key_ita = persona.periodo
        key_code = {
            "giornaliero": "daily",
            "settimanale": "weekly",
            "mensile": "monthly",
            "annuale": "yearly",
        }.get(persona.periodo, persona.periodo)

        for k in (key_ita, key_code):
            if k in periodi and isinstance(periodi[k], dict):
                return periodi[k]

    # 3) Ricerca ricorsiva fallback
    def _search(d: Any) -> Optional[Dict[str, Any]]:
        if isinstance(d, dict):
            keys = set(d.keys())
            if "date_range" in keys or "aspetti_rilevanti" in keys or "metriche_grafico" in keys:
                return d
            for v in d.values():
                found = _search(v)
                if found:
                    return found
        elif isinstance(d, list):
            for item in d:
                found = _search(item)
                if found:
                    return found
        return None

    found = _search(pipe)
    return found or {}


def _cleanup_period_block_for_ai(period_block: Dict[str, Any], persona: Persona) -> Dict[str, Any]:
    """
    Pulizia lato AI:
    - elimina SEMPRE i quincunx/quincunce dagli aspetti_rilevanti
    - per l'annuale: toglie la Luna dai pianeti_prevalenti
    """
    periodo = persona.periodo.lower()
    cleaned = dict(period_block)

    # ---- ASPETTI: togliamo i quincunx ovunque ----
    aspetti = list(cleaned.get("aspetti_rilevanti") or [])
    new_aspetti = []
    for a in aspetti:
        tipo = (a.get("aspetto") or a.get("tipo") or "").lower()
        if "quincun" in tipo:
            # niente quincunce nel feed AI
            continue
        new_aspetti.append(a)
    cleaned["aspetti_rilevanti"] = new_aspetti

    # ---- PIANETI PREVALENTI: per l'annuale, togliamo la Luna ----
    pian_prev = list(cleaned.get("pianeti_prevalenti") or [])
    if periodo.startswith("ann"):
        new_p = []
        for p in pian_prev:
            nome = (p.get("pianeta") or p.get("nome") or "")
            if nome == "Luna":
                continue
            new_p.append(p)
        cleaned["pianeti_prevalenti"] = new_p

    return cleaned

def build_debug_kb_hooks(
    period_block: Dict[str, Any],
    tema: Dict[str, Any],
    profilo_natale: Dict[str, Any],
    persona: Persona,
) -> Dict[str, Any]:
    """
    KB di debug: costruisce un combined_markdown leggibile basato su:
    - pianeti_prevalenti
    - aspetti_rilevanti
    - profilo_natale

    Shape compatibile con l'idea di KB reale:
    {
      "pianeti_prevalenti": [...],
      "aspetti_rilevanti": [...],
      "combined_markdown": "..."
    }
    """
    pianeti_prev = period_block.get("pianeti_prevalenti") or []
    aspetti = period_block.get("aspetti_rilevanti") or []

    lines: List[str] = []

    lines.append(f"# Contesto astrologico per {persona.nome}")
    lines.append(f"Periodo: {persona.periodo} — Tier: {persona.tier}")
    lines.append("")

    # ---------------- PIANETI PREVALENTI ----------------
    if pianeti_prev:
        lines.append("## Pianeti prevalenti nel periodo")
        for p in pianeti_prev:
            nome = p.get("pianeta") or p.get("nome") or "?"
            score = p.get("score_periodo")
            casa = p.get("casa_natale_transito")
            prima = p.get("prima_occorrenza")
            parts = [f"- {nome}"]
            if casa is not None:
                parts.append(f"in casa {casa}")
            if score is not None:
                parts.append(f"(peso periodo: {round(score, 3)})")
            if prima:
                parts.append(f"prima attivazione: {prima}")
            lines.append(" ".join(parts))
        lines.append("")

    # ---------------- ASPETTI RILEVANTI ----------------
    if aspetti:
        lines.append("## Aspetti chiave del periodo")
        for a in aspetti:
            tr = a.get("pianeta_transito") or "?"
            nat = a.get("pianeta_natale") or "?"
            asp = a.get("aspetto") or a.get("tipo") or "?"
            n_snap = a.get("n_snapshot")
            score_rel = a.get("score_rilevanza")
            riga = f"- {tr} {asp} {nat}"
            if n_snap is not None:
                riga += f" (presente in {n_snap} snapshot)"
            if score_rel is not None:
                riga += f", rilevanza: {round(score_rel, 3)}"
            lines.append(riga)

        # dettagli delle occorrenze
        lines.append("")
        lines.append("### Dettagli delle occorrenze principali")
        for a in aspetti:
            tr = a.get("pianeta_transito") or "?"
            nat = a.get("pianeta_natale") or "?"
            asp = a.get("aspetto") or a.get("tipo") or "?"
            occs = a.get("occorrenze") or []
            for occ in occs:
                dt = occ.get("datetime")
                orb = occ.get("orb")
                score_def = occ.get("score_definitivo")
                lines.append(
                    f"- {dt}: {tr} {asp} {nat} "
                    f"(orb≈{round(orb, 3) if orb is not None else '?'}; "
                    f"score={round(score_def, 3) if score_def is not None else '?'})"
                )
        lines.append("")

    # ---------------- PROFILO NATALE (sintetico) ----------------
    if profilo_natale:
        lines.append("## Profilo natale sintetico (pesi pianeti)")
        for nome, peso in sorted(profilo_natale.items(), key=lambda x: -x[1]):
            lines.append(f"- {nome}: peso {peso}")
        lines.append("")

    combined_md = "\n".join(lines) if lines else ""

    return {
        "pianeti_prevalenti": pianeti_prev,
        "aspetti_rilevanti": aspetti,
        "combined_markdown": combined_md,
    }
# =========================================================
# COSTRUZIONE OROSCOPO_STRUCT
# =========================================================

def build_oroscopo_struct_from_pipe(pipe: Dict[str, Any], persona: Persona) -> Dict[str, Any]:
    # Estratti di base dalla pipeline
    tema = pipe.get("tema_natale") or {}
    profilo_natale = pipe.get("profilo_natale") or {}
    meta_pipe = pipe.get("meta") or {}

    # Debug struttura principale della pipe
    print("\n######## DEBUG PIPE KEYS ########")
    print(list(pipe.keys()))
    print("#################################\n")

    # Troviamo il blocco di periodo giusto (settimanale, mensile, ecc.)
    periodo_output = _pick_period_block(pipe, persona) or {}

    print("\n================= DEBUG PERIODO_OUTPUT =================")
    print("LABEL:", periodo_output.get("label"))
    print("DATE_RANGE:", periodo_output.get("date_range"))
    samples = (periodo_output.get("metriche_grafico") or {}).get("samples", [])
    print("SNAPSHOT_COUNT:", len(samples))
    print("PIANETI_PREVALENTI:", periodo_output.get("pianeti_prevalenti"))
    print("ASPETTI_RILEVANTI:", periodo_output.get("aspetti_rilevanti"))
    print("=======================================================\n")

    # Date e sottoperiodi
    date_range = periodo_output.get("date_range") or {}
    sottoperiodi = generate_subperiods(persona.periodo, persona.tier, date_range)

    print("---- SOTTOPERIODI GENERATI ----")
    for sp in sottoperiodi:
        print(sp)
    print("-------------------------------\n")

    # Costruiamo il blocco periodo "raw"
    period_block_raw = {
        "label": periodo_output.get("label"),
        "date_range": date_range,
        "sottoperiodi": sottoperiodi,
        "aspetti_rilevanti": periodo_output.get("aspetti_rilevanti", []),
        "metriche_grafico": periodo_output.get("metriche_grafico", {}),
        "pianeti_prevalenti": periodo_output.get("pianeti_prevalenti", []),
    }

    # Pulizia lato AI (quincunx, Luna annuale, ecc.)
    period_block = _cleanup_period_block_for_ai(period_block_raw, persona)

    print("---- PERIOD_BLOCK COMPLETO ----")
    print(json.dumps(period_block, indent=2, ensure_ascii=False)[:2000])
    print("--------------------------------\n")

    # 🔥 Costruiamo SEMPRE la KB di debug
    kb_hooks = build_debug_kb_hooks(
        period_block=period_block,
        tema=tema,
        profilo_natale=profilo_natale,
        persona=persona,
    )

    kb_md = (kb_hooks.get("combined_markdown") or "")[:1000]
    print("---- KB (estratto) ----")
    print(kb_md)
    print("------------------------\n")

    # Oroscopo_struct finale che va al payload AI
    oroscopo_struct = {
        "meta": {
            "nome": persona.nome,
            "citta": persona.citta,
            "data_nascita": persona.data,
            "ora_nascita": persona.ora,
            "tier": persona.tier,
            "scope": "oroscopo_multi_snapshot",
            "lang": "it",
        },
        "tema": tema,
        "profilo_natale": profilo_natale,
        "kb_hooks": kb_hooks,
        "periodi": {
            persona.periodo: period_block
        },
    }

    print("[DEBUG PAYLOAD_AI] FINITO OROSCOPO_STRUCT:")
    print(json.dumps(oroscopo_struct, indent=2, ensure_ascii=False)[:2000])
    print("========================================================\n")

    return oroscopo_struct

# =========================================================
# CALL BACKEND
# =========================================================

def call_backend(persona: Persona, payload_ai: Dict[str, Any]) -> Dict[str, Any]:
    body = {
        "scope": "oroscopo_ai",
        "tier": persona.tier,
        "periodo": persona.periodo,
        "payload_ai": payload_ai,
    }
    print(f"\n=== CHIAMATA /oroscopo_ai ({persona.periodo}, {persona.tier}) ===")
    r = requests.post(ENDPOINT, json=body, timeout=90)
    print("HTTP:", r.status_code)
    if r.status_code != 200:
        print(r.text[:2000])
        return {}
    return r.json()


# =========================================================
# MAIN
# =========================================================

def main():
    print("=== TEST ASTROBOT MULTI-PERIODO ===")
    print("Backend:", ENDPOINT)

    for idx, persona in enumerate(PERSONE_TEST):
        print("\n============================================================")
        print(f"TEST: {persona.periodo.upper()} / {persona.tier.upper()}")
        print("============================================================")

        print("[1] Pipeline AstroBot…")
        pipe = run_oroscopo_multi_snapshot(
            periodo=persona.periodo,
            tier=persona.tier,
            citta=persona.citta,
            data_nascita=persona.data,
            ora_nascita=persona.ora,
            raw_date=TODAY,
        )

        print("[2] Costruzione oroscopo_struct…")
        oro_struct = build_oroscopo_struct_from_pipe(pipe, persona)

        period_code = {
            "giornaliero": "daily",
            "settimanale": "weekly",
            "mensile": "monthly",
            "annuale": "yearly",
        }.get(persona.periodo, "daily")

        print("[3] Costruzione payload AI…")
        payload = build_oroscopo_payload_ai(
            oroscopo_struct=oro_struct,
            lang="it",
            period_code=period_code,
        )

        print("[4] Chiamata backend…")
        resp = call_backend(persona, payload)
        if resp:
            print("[5] Analisi risposta AI…")
            analyze_response(persona, resp)

        if idx != len(PERSONE_TEST) - 1:
            print("\n[WAIT] 10 secondi…\n")
            time.sleep(10)

    print("\n=== FINE TEST ===")


if __name__ == "__main__":
    main()
