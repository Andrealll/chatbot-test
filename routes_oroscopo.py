# routes_oroscopo.py - nuova versione

from datetime import datetime
from typing import List, Dict, Any, Optional

from fastapi import APIRouter
from pydantic import BaseModel
from astrobot_core.metodi import call_ai_model  # usa il client Groq già pronto
from pydantic import BaseModel

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

@router.post("/oroscopo_ai", summary="Oroscopo AI via Groq")
def oroscopo_ai_endpoint(req: OroscopoAIRequest):
    """
    Usa il payload_ai (meta + periodi + kb) per chiamare Groq e ottenere
    un testo di interpretazione dell'oroscopo per il periodo richiesto.
    """
    t0 = datetime.now()

    payload_ai = req.payload_ai or {}
    meta = payload_ai.get("meta", {}) or {}
    periodi = payload_ai.get("periodi", {}) or {}
    kb = payload_ai.get("kb", {}) or {}

    periodo_key = req.periodo
    periodo_data = periodi.get(periodo_key, {}) or {}

    # Testo della KB (già limitato a livello di payload_ai)
    kb_text = kb.get("combined_markdown", "") or ""
    # Nel dubbio, un ulteriore hard-limit di sicurezza
    kb_text = kb_text[:16000]

    # Intensità: per ora stub, puoi raffinarle più avanti
    intensities = {
        "energy": 0.5,
        "emotions": 0.5,
        "relationships": 0.5,
        "work": 0.5,
        "luck": 0.5,
    }

    nome = meta.get("nome") or "la persona"
    label_periodo = periodo_data.get("label") or periodo_key

    # Costruiamo il prompt per Groq
    system_msg = {
        "role": "system",
        "content": (
            "Sei un astrologo professionista. "
            "Scrivi in italiano, con tono empatico, chiaro e concreto. "
            "Non inventare concetti fuori da ciò che ti viene fornito; "
            "usa solo le informazioni astrologiche che ricevi in input."
        ),
    }

    # Inseriamo meta + periodo + KB testuale
    user_content_parts = [
        f"Oroscopo {label_periodo} per {nome}.",
        "",
        "--- META ---",
        repr(meta),
        "",
        f"--- DATI PERIODO ({label_periodo}) ---",
        repr(periodo_data),
        "",
        "--- TESTO DALLA KNOWLEDGE BASE ---",
        kb_text,
        "",
        (
            "Scrivi un oroscopo strutturato in 4-8 paragrafi brevi, "
            "con consigli pratici e centrati sugli aspetti indicati. "
            "Non elencare i transiti in modo tecnico, ma integra il loro significato nel testo."
        ),
    ]
    user_msg = {
        "role": "user",
        "content": "\n".join(user_content_parts),
    }

    # Chiamata a Groq usando il wrapper già presente in astrobot_core.metodi
    testo_ai = call_ai_model(
        [system_msg, user_msg],
        max_tokens=900,
    )

    elapsed = round((datetime.now() - t0).total_seconds(), 3)

    # Per ora non rimandiamo pianeti_periodo/aspetti_rilevanti (puoi arricchire in seguito)
    return {
        "status": "ok",
        "scope": periodo_key,
        "elapsed": elapsed,
        "intensities": intensities,
        "pianeti_periodo": [],
        "aspetti_rilevanti": [],
        "interpretazione_AI": testo_ai,
    }


