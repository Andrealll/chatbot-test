# routes_oroscopo.py - nuova versione
import requests
from datetime import datetime
from typing import List, Dict, Any, Optional

from fastapi import APIRouter, HTTPException

from pydantic import BaseModel, Field
from astrobot_core.metodi import call_ai_model  # usa il client Groq già pronto
from pydantic import BaseModel
import os
import time
import json
from typing import Any, Dict, List, Literal, Optional

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
#  Modelli Pydantic
# =========================================================

class Aspetto(BaseModel):
    pianetaA: str
    pianetaB: str
    tipo: str
    orb: float
    peso: float  # peso dell'aspetto (già calcolato dal core, se disponibile)


class OroscopoRequest(BaseModel):
    scope: str  # "giornaliero" | "settimanale" | "mensile" | "annuale"
    # tema natale (almeno: pianeti_decod, asc_mc_case)
    tema: Dict[str, Any]
    # posizioni attuali dei pianeti (transiti) per l'oroscopo:
    # stessi campi di pianeti_decod (segno, gradi_segno, gradi_eclittici, retrogrado, ...)
    pianeti_transito: Optional[Dict[str, Dict[str, Any]]] = None
    # opzionale: lista aspetti già calcolata dal core (pianetaA/B, tipo, orb, peso)
    aspetti: Optional[List[Aspetto]] = None

class OroscopoAIRequest(BaseModel):
    """
    Richiesta per interpretazione AI dell'oroscopo multi-snapshot.

    Ci aspettiamo che `payload_ai` sia quello prodotto da `build_oroscopo_payload_ai`
    (meta + periodi + kb + kb_hooks).
    """
    scope: str = "oroscopo_ai"
    tier: str = "free"
    periodo: str  # "giornaliero" | "settimanale" | "mensile" | "annuale"
    payload_ai: Dict[str, Any]

class OroscopoAIRequest(BaseModel):
    scope: str = "oroscopo_ai"
    tier: Literal["free", "premium"]
    periodo: Literal["giornaliero", "settimanale", "mensile", "annuale"]
    payload_ai: Dict[str, Any]


class PianetaPeriodo(BaseModel):
    pianeta: str
    score_periodo: float
    fattore_natale: float
    casa_natale_transito: Optional[int] = None
    prima_occorrenza: str


class AspettoPeriodo(BaseModel):
    pianeta_transito: str
    pianeta_natale: str
    aspetto: str
    score_rilevanza: float
    orb_min: float
    n_snapshot: int


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
#  Funzioni di utilità
# =========================================================

def normalizza_scope(scope: str) -> str:
    """Normalizza scope per sicurezza."""
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
    """Ritorna i pianeti con peso >= SOGLIA_PESO per lo scope indicato."""
    scope = normalizza_scope(scope)
    pesi_scope = PESI_PIANETI_PER_PERIODO.get(scope, {})
    return [p for p, w in pesi_scope.items() if w >= SOGLIA_PESO]


def calcola_casa_equal(gradi_eclittici: float, asc_mc_case: Dict[str, Any]) -> Optional[int]:
    """
    Calcola la casa natale in sistema equal, usando ASC e la longitudine eclittica del pianeta.
    Ritorna un intero 1..12 oppure None se manca qualcosa.
    """
    if not asc_mc_case:
        return None

    asc = asc_mc_case.get("ASC")
    sistema = asc_mc_case.get("sistema_case", "").lower()

    if asc is None or sistema != "equal":
        return None

    # distanza dal grado dell'ASC lungo lo zodiaco
    delta = (gradi_eclittici - asc) % 360.0
    casa = int(delta // 30.0) + 1  # 0–29 → 1, 30–59 → 2, ecc.

    if casa < 1 or casa > 12:
        casa = ((casa - 1) % 12) + 1

    return casa


def estrai_pianeti_periodo(
    pianeti_transito: Dict[str, Dict[str, Any]],
    asc_mc_case: Dict[str, Any],
    scope: str,
) -> List[Dict[str, Any]]:
    """
    Estrae per lo scope:
      - solo pianeti con peso >= SOGLIA_PESO
      - segno, gradi nel segno (DI TRANSITO)
      - casa natale (calcolata da ASC equal houses del tema natale)
    """
    scope = normalizza_scope(scope)
    pianeti_sel = pianeti_rilevanti(scope)
    pesi_scope = PESI_PIANETI_PER_PERIODO[scope]

    risultati: List[Dict[str, Any]] = []

    for nome in pianeti_sel:
        if nome not in pianeti_transito:
            continue

        dati = pianeti_transito[nome]
        gradi_segno = dati.get("gradi_segno")
        gradi_eclittici = dati.get("gradi_eclittici")

        casa = None
        if gradi_eclittici is not None:
            casa = calcola_casa_equal(gradi_eclittici, asc_mc_case)

        risultati.append({
            "nome": nome,
            "peso_periodo": pesi_scope.get(nome),
            "segno": dati.get("segno"),
            "gradi": gradi_segno,
            "casa": casa,
        })

    return risultati


def filtra_aspetti_rilevanti(
    aspetti: List[Dict[str, Any]],
    scope: str,
    top_n: int = 3,
) -> List[Dict[str, Any]]:
    """
    Filtra e ordina gli aspetti:
      - solo tra pianeti con peso >= SOGLIA_PESO nello scope
      - ordinati per "peso" aspetto
      - restituisce i primi top_n
    """
    scope = normalizza_scope(scope)
    pesi_scope = PESI_PIANETI_PER_PERIODO[scope]

    def pianeta_ok(nome: str) -> bool:
        return pesi_scope.get(nome, 0.0) >= SOGLIA_PESO

    # 1) solo aspetti tra pianeti "pesanti"
    aspetti_filtrati = [
        a for a in aspetti
        if pianeta_ok(a["pianetaA"]) and pianeta_ok(a["pianetaB"])
    ]

    # 2) ordina per peso aspetto
    aspetti_ordinati = sorted(
        aspetti_filtrati,
        key=lambda a: a.get("peso", 0.0),
        reverse=True
    )[:top_n]

    # 3) aggiungi info sui pesi dei pianeti
    for a in aspetti_ordinati:
        a["peso_pianetaA"] = pesi_scope.get(a["pianetaA"])
        a["peso_pianetaB"] = pesi_scope.get(a["pianetaB"])

    return aspetti_ordinati


def calcola_intensita_stub(aspetti_rilevanti: List[Dict[str, Any]]) -> Dict[str, float]:
    """
    Stub semplice per calcolare le intensità a partire dagli aspetti selezionati.
    Lo teniamo basico: il motore AI userà soprattutto pianeti_periodo + aspetti_rilevanti.
    """
    if not aspetti_rilevanti:
        return {
            "energy": 0.5,
            "emotions": 0.5,
            "relationships": 0.5,
            "work": 0.5,
            "luck": 0.5,
        }

    somma_pesi = sum(a.get("peso", 0.0) for a in aspetti_rilevanti) or 1.0
    base = min(1.0, somma_pesi / 3.0)

    # distribuzione molto semplice
    return {
        "energy": max(0.0, min(1.0, base)),
        "emotions": max(0.0, min(1.0, base * 1.05)),
        "relationships": max(0.0, min(1.0, base * 0.95)),
        "work": max(0.0, min(1.0, base * 0.9)),
        "luck": max(0.0, min(1.0, base * 1.1)),
    }


# =========================================================
#  Endpoint principale oroscopo
# =========================================================

@router.post("/oroscopo")
def oroscopo(req: OroscopoRequest):
    """
    Calcola l'output strutturato per l'oroscopo, pronto per il motore AI.

    Input atteso:
      - scope: "giornaliero" | "settimanale" | "mensile" | "annuale"
      - tema: output del /tema, deve contenere almeno:
          tema["pianeti_decod"] = {
              "Sole": {"segno": ..., "gradi_segno": ..., "gradi_eclittici": ...},
              ...
          }
          tema["asc_mc_case"] = {
              "ASC": ...,
              "sistema_case": "equal",
              ...
          }
      - pianeti_transito (opzionale):
          posizioni attuali dei pianeti, con stessa struttura di pianeti_decod
          (se assente, si usano i pianeti del tema natale come fallback)
      - aspetti: opzionale, lista di Aspetto:
          {
            "pianetaA": "Luna",
            "pianetaB": "Sole",
            "tipo": "trigono",
            "orb": 1.2,
            "peso": 0.85
          }

    Output:
      {
        "status": "ok",
        "scope": ...,
        "elapsed": ...,
        "intensities": {...},
        "pianeti_periodo": [...],
        "aspetti_rilevanti": [...],
        "interpretazione_AI": null
      }
    """
    t0 = datetime.now()
    scope = normalizza_scope(req.scope)

    tema = req.tema or {}
    pianeti_natal = tema.get("pianeti_decod", {})
    asc_mc_case = tema.get("asc_mc_case", {})

    # Se non vengono passati esplicitamente, usiamo come fallback i pianeti natali
    pianeti_transito = req.pianeti_transito or pianeti_natal

    # 1) pianeti del periodo (peso >= 0.7) con segno/gradi DI TRANSITO e casa natale
    pianeti_periodo = estrai_pianeti_periodo(
        pianeti_transito=pianeti_transito,
        asc_mc_case=asc_mc_case,
        scope=scope,
    )

    # 2) aspetti (se forniti) -> top 3 rilevanti
    aspetti_list_dict: List[Dict[str, Any]] = []
    if req.aspetti:
        # trasformo i modelli Pydantic in dict normali
        aspetti_list_dict = [a.dict() for a in req.aspetti]

    aspetti_rilevanti = filtra_aspetti_rilevanti(
        aspetti=aspetti_list_dict,
        scope=scope,
        top_n=3,
    )

    # 3) intensità (stub per ora, ma coerente)
    intensities = calcola_intensita_stub(aspetti_rilevanti)

    elapsed = round((datetime.now() - t0).total_seconds(), 3)

    return {
        "status": "ok",
        "scope": scope,
        "elapsed": elapsed,
        "intensities": intensities,
        "pianeti_periodo": pianeti_periodo,
        "aspetti_rilevanti": aspetti_rilevanti,
        "interpretazione_AI": None,
    }



def _extract_period_block(payload_ai: Dict[str, Any], periodo: str) -> Dict[str, Any]:
    periodi = payload_ai.get("periodi") or {}
    if periodo not in periodi:
        raise KeyError(f"Periodo '{periodo}' non presente in payload_ai.periodi.")
    return periodi[periodo]


def _summary_intensities(period_block: Dict[str, Any]) -> Dict[str, float]:
    """
    Media delle intensities sui vari snapshot.
    Se manca qualcosa, fallback a 0.5.
    """
    metriche_grafico = period_block.get("metriche_grafico") or {}
    samples = metriche_grafico.get("samples") or []
    if not samples:
        return {
            "energy": 0.5,
            "emotions": 0.5,
            "relationships": 0.5,
            "work": 0.5,
            "luck": 0.5,
        }

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
        return {
            "energy": 0.5,
            "emotions": 0.5,
            "relationships": 0.5,
            "work": 0.5,
            "luck": 0.5,
        }

    return {k: v / n for k, v in acc.items()}


def _summary_aspetti(period_block: Dict[str, Any], max_n: int = 10) -> List[Dict[str, Any]]:
    """
    Prende aspetti_rilevanti già ordinati dal core e li taglia a max_n.
    """
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
    """
    Usa direttamente pianeti_prevalenti dal core (già ordinati).
    """
    return list(period_block.get("pianeti_prevalenti") or [])


def _period_code_from_label(periodo: str) -> str:
    return {
        "giornaliero": "daily",
        "settimanale": "weekly",
        "mensile": "monthly",
        "annuale": "yearly",
    }.get(periodo, "daily")
def _extract_period_block(payload_ai: Dict[str, Any], periodo: str) -> Dict[str, Any]:
    periodi = payload_ai.get("periodi") or {}
    if periodo not in periodi:
        raise KeyError(f"Periodo '{periodo}' non presente in payload_ai.periodi.")
    return periodi[periodo]


def _summary_intensities(period_block: Dict[str, Any]) -> Dict[str, float]:
    """
    Media delle intensities sui vari snapshot.
    Se manca qualcosa, fallback a 0.5.
    """
    metriche_grafico = period_block.get("metriche_grafico") or {}
    samples = metriche_grafico.get("samples") or []
    if not samples:
        return {
            "energy": 0.5,
            "emotions": 0.5,
            "relationships": 0.5,
            "work": 0.5,
            "luck": 0.5,
        }

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
        return {
            "energy": 0.5,
            "emotions": 0.5,
            "relationships": 0.5,
            "work": 0.5,
            "luck": 0.5,
        }

    return {k: v / n for k, v in acc.items()}


def _summary_aspetti(period_block: Dict[str, Any], max_n: int = 10) -> List[Dict[str, Any]]:
    """
    Prende aspetti_rilevanti già ordinati dal core e li taglia a max_n.
    """
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
    """
    Usa direttamente pianeti_prevalenti dal core (già ordinati).
    """
    return list(period_block.get("pianeti_prevalenti") or [])


def _period_code_from_label(periodo: str) -> str:
    return {
        "giornaliero": "daily",
        "settimanale": "weekly",
        "mensile": "monthly",
        "annuale": "yearly",
    }.get(periodo, "daily")
def _build_groq_messages(req: OroscopoAIRequest, payload_ai: Dict[str, Any]) -> List[Dict[str, str]]:
    meta = payload_ai.get("meta") or {}
    period_block = _extract_period_block(payload_ai, req.periodo)

    intensities = _summary_intensities(period_block)
    pianeti = _summary_pianeti(period_block)
    aspetti = _summary_aspetti(period_block, max_n=20)

    kb_md = ((payload_ai.get("kb") or {}).get("combined_markdown")) or ""
    # safety: tagliamo comunque a ~16K char
    kb_md = kb_md[:16000]

    system = {
        "role": "system",
        "content": (
            "Sei AstroBot, un'AI che scrive oroscopi personalizzati usando un tema natale, "
            "una selezione di transiti e una knowledge base astrologica in markdown. "
            "Rispondi sempre SOLO in JSON valido compatibile con lo schema richiesto. "
            "Non includere testo libero fuori dal JSON."
        ),
    }

    user_payload = {
        "meta": meta,
        "tier": req.tier,
        "periodo": req.periodo,
        "period_code": _period_code_from_label(req.periodo),
        "intensities": intensities,
        "pianeti_prevalenti": pianeti,
        "aspetti_rilevanti": aspetti,
        "kb_markdown": kb_md,
    }

    user = {
        "role": "user",
        "content": (
            "Devi generare un oroscopo astrologico in italiano per l'utente indicato in 'meta', "
            "per il periodo specificato in 'periodo'.\n\n"
            "Hai a disposizione:\n"
            "- 'intensities': valori 0..1 per energy/emotions/relationships/work/luck\n"
            "- 'pianeti_prevalenti': pianeti di transito chiave sul periodo\n"
            "- 'aspetti_rilevanti': lista di aspetti transito→natale più importanti\n"
            "- 'kb_markdown': estratti di knowledge base astrologica già filtrata.\n\n"
            "1) Leggi con attenzione il payload JSON seguente.\n"
            "2) Usa kb_markdown come base concettuale, ma non copiarla parola per parola.\n"
            "3) Scrivi un oroscopo strutturato in sezioni JSON, ad es.: "
            "{ 'sintesi': '...', 'amore': '...', 'lavoro': '...', 'crescita_personale': '...' }.\n"
            "4) Cita esplicitamente i transiti principali (pianeti e aspetti) quando rilevante.\n"
            "5) Adatta il livello di dettaglio al tier: 'free' = breve/essenziale, 'premium' = ricco e articolato.\n\n"
            "Restituisci SOLO un oggetto JSON con questa struttura generale:\n"
            "{\n"
            '  "sintesi": string,\n'
            '  "amore": string,\n'
            '  "lavoro": string,\n'
            '  "crescita_personale": string,\n'
            '  "consigli_pratici": [string, ...]\n'
            "}\n\n"
            "Ecco il payload da usare:\n"
            f"{json.dumps(user_payload, ensure_ascii=False)}"
        ),
    }

    return [system, user]

@router.post("/oroscopo_ai", response_model=OroscopoAIResponse)
async def oroscopo_ai(req: OroscopoAIRequest) -> OroscopoAIResponse:
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

    groq_body = {
        "model": "llama-3.1-70b-versatile",
        "messages": messages,
        "max_tokens": 900 if req.tier == "premium" else 450,
        "temperature": 0.9,
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
        # qui vedi eventuali 401/429/503 di Groq
        raise HTTPException(
            status_code=502,
            detail=f"Groq HTTP {resp.status_code}: {resp.text[:500]}",
        )

    data = resp.json()
    content = (((data.get("choices") or [{}])[0].get("message") or {}).get("content")) or "{}"

    try:
        interpretazione = json.loads(content)
    except Exception:
        # fallback se il modello non rispetta alla lettera il JSON only
        interpretazione = {"raw": content}

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
