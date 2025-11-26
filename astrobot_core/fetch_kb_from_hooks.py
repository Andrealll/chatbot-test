"""
fetch_kb_from_hooks.py

Modulo per:
- leggere i kb_hooks generati da oroscopo_payload_ai.py
- interrogare Supabase sulle tabelle KB
- restituire i content_md combinati in un unico markdown

Livelli di controllo volume:
1) Limite sul numero di voci da interrogare:
   - max_entries_per_section (dict opzionale per tipo: case, pianeti, ...)
   - max_total_entries (limite globale)

2) Limite qualitativo sui capitoli della KB:
   - per ogni tabella si possono definire allowed_headings,
     diversi per tier free/premium, per accorciare il testo
     senza perdere le parti più importanti.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple, Iterable

from supabase import create_client, Client


# =========================================================
#  Configurazione mapping hooks → tabelle KB
# =========================================================

@dataclass(frozen=True)
class KbTableConfig:
    hook_key: str         # chiave di kb_hooks, es. "case"
    table_name: str       # nome tabella Supabase, es. "kb_case"
    id_columns: Tuple[str, ...]        # colonne chiave
    default_max_entries: Optional[int] = None   # limite di default per sezione
    # default headings, usati come fallback se non definiti per tier
    allowed_headings: Optional[Tuple[str, ...]] = None


# ORDINE DI PRIORITÀ (IMPORTANTISSIMO):
# 1) transiti_pianeti (core)
# 2) pianeti_case
# 3) segni
# 4) pianeti
# 5) case
KB_TABLES: Dict[str, KbTableConfig] = {
    "transiti_pianeti": KbTableConfig(
        hook_key="transiti_pianeti",
        table_name="kb_transiti_pianeti",
        id_columns=("transit_planet", "natal_planet", "aspect"),
        default_max_entries=6,
        # headings specifici gestiti via HEADINGS_POLICY
        allowed_headings=None,
    ),
    "pianeti_case": KbTableConfig(
        hook_key="pianeti_case",
        table_name="kb_pianeti_case",
        id_columns=("transit_planet", "natal_house"),
        default_max_entries=6,
        allowed_headings=None,
    ),
    "segni": KbTableConfig(
        hook_key="segni",
        table_name="kb_segni",
        id_columns=("nome",),
        default_max_entries=6,
        allowed_headings=None,
    ),
    "pianeti": KbTableConfig(
        hook_key="pianeti",
        table_name="kb_pianeti",
        id_columns=("nome",),
        default_max_entries=6,
        allowed_headings=None,
    ),
    "case": KbTableConfig(
        hook_key="case",
        table_name="kb_case",
        id_columns=("numero",),
        default_max_entries=4,
        # fallback: per le Case teniamo solo le parti più utili
        allowed_headings=(
            "Parole chiave",
            "Ambiti di vita",
            "Analogie essenziali",
        ),
    ),
}


# =========================================================
#  Policy headings per tier (free/premium)
#  (se un heading non combacia, il filtro cade in fallback)
# =========================================================

HEADINGS_POLICY: Dict[str, Dict[str, Tuple[str, ...]]] = {
    "free": {
        # Case: sintetico
        "case": (
            "Parole chiave",
            "Ambiti di vita",
        ),
        # Pianeti: essenziale
        "pianeti": (
            "Parole chiave",
            "Temi psicologici",
        ),
        # Segni: molto essenziale
        "segni": (
            "Parole chiave",
        ),
        # Transiti: core sintetico
        "transiti_pianeti": (
            "Sintesi del transito",
            "Consigli pratici",
        ),
        # Pianeti_case: sintetico
        "pianeti_case": (
            "Sintesi pianeta in casa",
        ),
    },
    "premium": {
        # Case: più ricco
        "case": (
            "Parole chiave",
            "Ambiti di vita",
            "Analogie essenziali",
        ),
        "pianeti": (
            "Parole chiave",
            "Temi psicologici",
            "Espressioni elevate",
            "Ombre e distorsioni",
        ),
        "segni": (
            "Parole chiave",
            "Psicologia di base",
            "Modalità espressiva",
        ),
        "transiti_pianeti": (
            "Sintesi del transito",
            "Effetti sul vissuto",
            "Tendenze interiori",
            "Consigli pratici",
        ),
        "pianeti_case": (
            "Sintesi pianeta in casa",
            "Temi di esperienza",
            "Sfide",
            "Risorse",
        ),
    },
}


# =========================================================
#  Client Supabase
# =========================================================

def get_supabase_client() -> Client:
    """Crea il client Supabase usando le env vars."""
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")

    if not url or not key:
        raise RuntimeError(
            "SUPABASE_URL o SUPABASE_SERVICE_ROLE_KEY non sono impostate nelle variabili d'ambiente."
        )

    return create_client(url, key)


# =========================================================
#  Funzioni di utilità: normalizzazione hooks
# =========================================================

def _normalize_hook_entries(raw_entries: Any, id_columns: Tuple[str, ...]) -> List[Dict[str, Any]]:
    """
    Normalizza i valori di kb_hooks in una lista di dict con le colonne richieste.

    Supporta:
    - lista di valori semplici (es. case: [1, 2, 7]) → mappati sulla prima colonna id_columns[0]
    - lista di dict completi (es. pianeti_case: [{"transit_planet": "...", "natal_house": 5}, ...])
    """
    if raw_entries is None:
        return []

    if not isinstance(raw_entries, list):
        raw_entries = [raw_entries]

    normalized: List[Dict[str, Any]] = []

    for entry in raw_entries:
        if isinstance(entry, dict):
            criteria = {col: entry.get(col) for col in id_columns if col in entry}
        else:
            criteria = {id_columns[0]: entry}

        if all(v is None for v in criteria.values()):
            continue

        normalized.append(criteria)

    return normalized


def _dedupe_entries(entries: List[Dict[str, Any]], id_columns: Tuple[str, ...]) -> List[Dict[str, Any]]:
    """Rimuove duplicati (stessa combinazione di colonne id)."""
    seen: set[Tuple[Any, ...]] = set()
    deduped: List[Dict[str, Any]] = []

    for e in entries:
        key = tuple(e.get(col) for col in id_columns)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(e)

    return deduped


# =========================================================
#  Funzioni di utilità: query KB + filtro capitoli
# =========================================================

def _query_kb_table(
    supabase: Client,
    cfg: KbTableConfig,
    entries: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Esegue i lookup sulla tabella indicata a partire da una lista di criteri.

    Ritorna una lista di righe (dict) contenenti almeno content_md.

    Compatibile sia con supabase-py "nuovo" (APIResponse con .data)
    sia con eventuali risposte dict-like.
    """
    rows: List[Dict[str, Any]] = []

    for criteria in entries:
        query = supabase.table(cfg.table_name).select("*")
        for col, value in criteria.items():
            query = query.eq(col, value)

        resp = query.execute()

        # Nuova gestione robusta:
        data = None

        # Caso supabase-py v2: APIResponse con attributo .data
        if hasattr(resp, "data"):
            data = resp.data
        # Caso "dict-like" (vecchie versioni o mock)
        elif isinstance(resp, dict):
            data = resp.get("data", [])

        if not data:
            continue

        # Se per qualche motivo non è una lista, normalizziamo a lista
        if not isinstance(data, list):
            data = [data]

        rows.extend(data)

    return rows




def _filter_content_by_headings(
    content_md: str,
    allowed_headings: Optional[Iterable[str]],
) -> str:
    """
    Filtra il markdown tenendo solo alcuni capitoli identificati dalle intestazioni:

    - '# Titolo'
    - '## Titolo'

    Se allowed_headings è None → ritorna content_md senza modifiche.
    Se non viene trovata nessuna sezione ammessa → ritorna l'originale (fall-back).
    """
    if not content_md:
        return ""

    if not allowed_headings:
        return content_md

    allowed_set = {h.strip().lower() for h in allowed_headings}

    lines = content_md.splitlines(keepends=False)

    # Gestione eventuale frontmatter iniziale (--- ... ---)
    frontmatter_lines: List[str] = []
    body_lines: List[str] = []
    in_frontmatter = False
    front_done = False

    for line in lines:
        if not front_done and line.strip() == "---":
            if not in_frontmatter:
                in_frontmatter = True
            else:
                in_frontmatter = False
                front_done = True
            frontmatter_lines.append(line)
            continue

        if in_frontmatter:
            frontmatter_lines.append(line)
        else:
            body_lines.append(line)

    selected_body: List[str] = []
    current_block: List[str] = []
    current_heading: Optional[str] = None
    blocks_to_keep: List[List[str]] = []

    def flush_block():
        if current_block and current_heading:
            title_norm = current_heading.strip().lower()
            if title_norm in allowed_set:
                blocks_to_keep.append(list(current_block))

    for line in body_lines:
        stripped = line.lstrip()

        if stripped.startswith("# "):
            flush_block()
            current_block = [line]
            current_heading = stripped[2:].strip()
        elif stripped.startswith("## "):
            flush_block()
            current_block = [line]
            current_heading = stripped[3:].strip()
        else:
            if current_block:
                current_block.append(line)
            else:
                continue

    flush_block()

    if not blocks_to_keep:
        return content_md  # fall-back

    selected_body = []
    for block in blocks_to_keep:
        selected_body.extend(block)
        selected_body.append("")

    result_lines: List[str] = []
    if frontmatter_lines:
        result_lines.extend(frontmatter_lines)
        result_lines.append("")

    result_lines.extend(selected_body)

    return "\n".join(result_lines).strip() + "\n"


# =========================================================
#  Funzione principale
# =========================================================

def fetch_kb_from_hooks(
    kb_hooks: Dict[str, Any],
    supabase: Optional[Client] = None,
    include_headings: bool = True,
    max_entries_per_section: Optional[Dict[str, int]] = None,
    max_total_entries: Optional[int] = None,
    filter_chapters: bool = True,
    tier: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Legge i kb_hooks, interroga Supabase, e restituisce:

    {
      "by_section": {
         "transiti_pianeti": [ {row1}, {row2}, ... ],
         "pianeti_case": [...],
         "segni": [...],
         "pianeti": [...],
         "case": [...],
      },
      "combined_markdown": "### Transiti Pianeti\\n...\\n\\n### Case\\n..."
    }

    Parametri di controllo volume
    -----------------------------
    max_entries_per_section : dict opzionale
        Es: {"case": 3, "pianeti": 5}
        - se presente, sovrascrive default_max_entries per quella sezione.

    max_total_entries : int opzionale
        Limite globale sul numero TOTALE di "entries" (somma di tutti gli hooks).

    filter_chapters : bool
        Se True, applica _filter_content_by_headings usando HEADINGS_POLICY
        per il tier free/premium (con fallback su allowed_headings di tabella).
    """
    if supabase is None:
        supabase = get_supabase_client()

    tier_norm = (tier or "free").strip().lower()
    if tier_norm not in {"free", "premium"}:
        tier_norm = "free"

    by_section: Dict[str, List[Dict[str, Any]]] = {}
    markdown_blocks: List[str] = []

    total_entries_used = 0

    for key, cfg in KB_TABLES.items():
        raw_entries = kb_hooks.get(cfg.hook_key)
        normalized = _normalize_hook_entries(raw_entries, cfg.id_columns)
        if not normalized:
            continue

        normalized = _dedupe_entries(normalized, cfg.id_columns)

        # -------- LIVELLO 1: limiti sul numero di voci da interrogare --------
        section_limit = None
        if max_entries_per_section and key in max_entries_per_section:
            section_limit = max_entries_per_section[key]
        elif cfg.default_max_entries is not None:
            section_limit = cfg.default_max_entries

        if max_total_entries is not None:
            remaining_global = max_total_entries - total_entries_used
            if remaining_global <= 0:
                break
            if section_limit is not None:
                section_limit = min(section_limit, remaining_global)
            else:
                section_limit = remaining_global

        if section_limit is not None and section_limit >= 0:
            normalized = normalized[:section_limit]

        total_entries_used += len(normalized)

        if not normalized:
            continue

        # -------- Query KB --------
        rows = _query_kb_table(supabase, cfg, normalized)
        if not rows:
            continue

        # -------- LIVELLO 2: filtro capitoli dentro ogni content_md --------
        processed_rows: List[Dict[str, Any]] = []

        # headings per tier/section
        tier_headings = HEADINGS_POLICY.get(tier_norm, {})
        section_headings = tier_headings.get(key)
        if not section_headings:
            section_headings = cfg.allowed_headings  # fallback

        for row in rows:
            row_copy = dict(row)
            content = row_copy.get("content_md")
            if content and filter_chapters and section_headings:
                row_copy["content_md"] = _filter_content_by_headings(content, section_headings)
            processed_rows.append(row_copy)

        by_section[key] = processed_rows

        section_texts = [
            r.get("content_md")
            for r in processed_rows
            if r.get("content_md")
        ]
        if not section_texts:
            continue

        if include_headings:
            title = key.replace("_", " ").title()
            block = f"### {title}\n\n" + "\n\n".join(section_texts)
        else:
            block = "\n\n".join(section_texts)

        markdown_blocks.append(block)

    combined_md = "\n\n---\n\n".join(markdown_blocks) if markdown_blocks else ""

    return {
        "by_section": by_section,
        "combined_markdown": combined_md,
    }


# =========================================================
#  Esecuzione da riga di comando (debug / test manuale)
# =========================================================

def _demo_kb_hooks() -> Dict[str, Any]:
    """Esempio di kb_hooks fittizio (puoi adattarlo a quello reale del payload AI)."""
    return {
        "case": [1, 7],
        "pianeti": ["Sole", "Luna"],
        "pianeti_case": [
            {"transit_planet": "Venere", "natal_house": 5},
        ],
        "segni": ["Cancro"],
        "transiti_pianeti": [
            {
                "transit_planet": "Saturno",
                "natal_planet": "Sole",
                "aspect": "quadratura",
            }
        ],
    }


if __name__ == "__main__":
    """
    Uso da terminale:

    1) Leggere kb_hooks da file JSON:
       python fetch_kb_from_hooks.py path/to/kb_hooks.json

    2) Oppure senza argomenti, usare un esempio demo:
       python fetch_kb_from_hooks.py
    """
    import sys
    from pathlib import Path

    if len(sys.argv) > 1:
        json_path = Path(sys.argv[1])
        if not json_path.exists():
            raise SystemExit(f"File non trovato: {json_path}")
        kb_hooks = json.loads(json_path.read_text(encoding="utf-8"))
    else:
        print("[fetch_kb_from_hooks] Nessun file passato, uso kb_hooks di demo.\n")
        kb_hooks = _demo_kb_hooks()

    result = fetch_kb_from_hooks(
        kb_hooks,
        max_entries_per_section={"case": 2},
        max_total_entries=10,
        filter_chapters=True,
        tier="free",
    )
    print("\n========== COMBINED MARKDOWN ==========\n")
    print(result["combined_markdown"])
