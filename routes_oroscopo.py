# routes_oroscopo.py - nuova versione

from datetime import datetime
from typing import List, Dict, Any, Optional

from fastapi import APIRouter
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
    # output del /tema (almeno: pianeti_decod, asc_mc_case)
    tema: Dict[str, Any]
    # opzionale: lista aspetti già calcolata dal core (pianetaA/B, tipo, orb, peso)
    aspetti: Optional[List[Aspetto]] = None


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
    pianeti_decod: Dict[str, Dict[str, Any]],
    asc_mc_case: Dict[str, Any],
    scope: str,
) -> List[Dict[str, Any]]:
    """
    Estrae per lo scope:
      - solo pianeti con peso >= SOGLIA_PESO
      - segno, gradi nel segno, casa natale (calcolata da ASC equal houses)
    """
    scope = normalizza_scope(scope)
    pianeti_sel = pianeti_rilevanti(scope)
    pesi_scope = PESI_PIANETI_PER_PERIODO[scope]

    risultati: List[Dict[str, Any]] = []

    for nome in pianeti_sel:
        if nome not in pianeti_decod:
            continue

        dati = pianeti_decod[nome]
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
    pianeti_decod = tema.get("pianeti_decod", {})
    asc_mc_case = tema.get("asc_mc_case", {})

    # 1) pianeti del periodo (peso >= 0.7) con segno, gradi, casa
    pianeti_periodo = estrai_pianeti_periodo(
        pianeti_decod=pianeti_decod,
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
