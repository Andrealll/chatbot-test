"""
transiti_pesatura.py

Logica di pesatura (intensità) dei transiti in base allo use case:
- oroscopo giornaliero (daily)
- oroscopo settimanale (weekly)
- oroscopo mensile (monthly)
- oroscopo annuale (yearly)

Si appoggia alle informazioni di:
- tipo di configurazione: generale / casa / aspetto
- pianeta di transito
- tipo di aspetto
- orb
- polarità (se presente nell'aspetto)
- fattori del tema natale (case, ruler ascendente, numero di aspetti stretti)
"""

from __future__ import annotations
from typing import Dict, Optional, List

# ---------------------------------------------------------------------------
# Costanti use case e tipi di configurazione
# ---------------------------------------------------------------------------

USE_CASE_DAILY = "daily"
USE_CASE_WEEKLY = "weekly"
USE_CASE_MONTHLY = "monthly"
USE_CASE_YEARLY = "yearly"

TIPO_CONFIG_GENERALE = "generale"
TIPO_CONFIG_CASA = "casa"
TIPO_CONFIG_ASPETTO = "aspetto"

# ---------------------------------------------------------------------------
# Pesi BASE per pianeta di transito per periodo (tabella fornita)
# ---------------------------------------------------------------------------
# Tabella originale:
#     daily  weekly  monthly yearly
# Luna       1       0.5    0      0
# Mercurio   0.75    1      0.2    0
# Venere     0.8     1      0.8    0
# Sole       0.7     0.9    1      0
# Marte      0.5     0.9    1      0.25
# Giove      0.3     0.7    0.7    1
# Saturno    0.3     0.5    0.6    1
# Urano      0.25    0.3    0.5    1
# Nettuno    0.25    0.3    0.5    0.8
# Plutone    0.25    0.3    0.5    0.5

PESO_PIANETA_TRANSITO: Dict[str, Dict[str, float]] = {
    USE_CASE_DAILY: {
        "Luna": 1.0,
        "Mercurio": 0.75,
        "Venere": 0.8,
        "Sole": 0.7,
        "Marte": 0.5,
        "Giove": 0.3,
        "Saturno": 0.3,
        "Urano": 0.25,
        "Nettuno": 0.25,
        "Plutone": 0.25,
    },
    USE_CASE_WEEKLY: {
        "Luna": 0.5,
        "Mercurio": 1.0,
        "Venere": 1.0,
        "Sole": 0.9,
        "Marte": 0.9,
        "Giove": 0.7,
        "Saturno": 0.5,
        "Urano": 0.3,
        "Nettuno": 0.3,
        "Plutone": 0.3,
    },
    USE_CASE_MONTHLY: {
        "Luna": 0.0,
        "Mercurio": 0.2,
        "Venere": 0.8,
        "Sole": 1.0,
        "Marte": 1.0,
        "Giove": 0.7,
        "Saturno": 0.6,
        "Urano": 0.5,
        "Nettuno": 0.5,
        "Plutone": 0.5,
    },
    USE_CASE_YEARLY: {
        "Luna": 0.0,
        "Mercurio": 0.0,
        "Venere": 0.0,
        "Sole": 0.0,
        "Marte": 0.25,
        "Giove": 1.0,
        "Saturno": 1.0,
        "Urano": 1.0,
        "Nettuno": 0.8,
        "Plutone": 0.5,
    },
}

# ---------------------------------------------------------------------------
# Pesi per tipo di configurazione (ruolo)
# ---------------------------------------------------------------------------
# Nota: qui manteniamo la stessa filosofia del notebook originale,
# aggiungendo WEEKLY con valori intermedi.

PESO_RUOLO: Dict[str, Dict[str, float]] = {
    USE_CASE_DAILY: {
        TIPO_CONFIG_GENERALE: 0.5,
        TIPO_CONFIG_CASA: 1.0,
        TIPO_CONFIG_ASPETTO: 1.0,
    },
    USE_CASE_WEEKLY: {
        # leggermente più peso alla tendenza generale rispetto al daily
        TIPO_CONFIG_GENERALE: 0.6,
        TIPO_CONFIG_CASA: 1.0,
        TIPO_CONFIG_ASPETTO: 0.95,
    },
    USE_CASE_MONTHLY: {
        TIPO_CONFIG_GENERALE: 0.7,
        TIPO_CONFIG_CASA: 1.0,
        TIPO_CONFIG_ASPETTO: 0.9,
    },
    USE_CASE_YEARLY: {
        TIPO_CONFIG_GENERALE: 0.9,
        TIPO_CONFIG_CASA: 1.0,
        TIPO_CONFIG_ASPETTO: 1.0,
    },
}

# ---------------------------------------------------------------------------
# Pesi per tipo di aspetto
# ---------------------------------------------------------------------------

PESO_ASPETTO: Dict[str, float] = {
    "congiunzione": 1.20,
    "opposizione": 1.10,
    "quadratura": 1.00,
    "trigono": 0.90,
    "sestile": 0.80,
    "quincunce": 0.70,
}

# ---------------------------------------------------------------------------
# Fattori orb per use case
# ---------------------------------------------------------------------------

def fattore_orb_daily(orb: float) -> float:
    if orb <= 0.2:
        return 1.40
    if orb <= 0.5:
        return 1.20
    if orb <= 1.0:
        return 1.00
    if orb <= 2.0:
        return 0.70
    return 0.40


def fattore_orb_weekly(orb: float) -> float:
    """
    Intermedio tra daily e monthly: gli aspetti molto stretti contano,
    ma c'è un po' più di tolleranza.
    """
    if orb <= 0.3:
        return 1.35
    if orb <= 0.7:
        return 1.15
    if orb <= 1.5:
        return 1.00
    if orb <= 2.5:
        return 0.80
    return 0.50


def fattore_orb_monthly(orb: float) -> float:
    if orb <= 0.5:
        return 1.30
    if orb <= 1.0:
        return 1.15
    if orb <= 2.0:
        return 1.00
    if orb <= 3.0:
        return 0.85
    if orb <= 4.0:
        return 0.70
    return 0.50


def fattore_orb_yearly(orb: float) -> float:
    if orb <= 0.5:
        return 1.20
    if orb <= 1.0:
        return 1.10
    if orb <= 2.0:
        return 1.00
    if orb <= 3.0:
        return 0.95
    if orb <= 4.0:
        return 0.90
    if orb <= 5.0:
        return 0.80
    return 0.60


def get_fattore_orb(use_case: str, orb: Optional[float]) -> float:
    if orb is None:
        return 1.0
    if use_case == USE_CASE_DAILY:
        return fattore_orb_daily(orb)
    if use_case == USE_CASE_WEEKLY:
        return fattore_orb_weekly(orb)
    if use_case == USE_CASE_MONTHLY:
        return fattore_orb_monthly(orb)
    if use_case == USE_CASE_YEARLY:
        return fattore_orb_yearly(orb)
    return 1.0

# ---------------------------------------------------------------------------
# Helpers per pesi pianeta / ruolo / aspetto
# ---------------------------------------------------------------------------

def _peso_pianeta(use_case: str, pianeta: str, tipo_config: str) -> float:
    """
    Pesa il pianeta di transito in base allo use_case.
    Per ora usiamo la stessa tabella per tutte le configurazioni
    (generale/casa/aspetto), modulata poi da PESO_RUOLO.
    """
    return PESO_PIANETA_TRANSITO.get(use_case, {}).get(pianeta, 0.0)


def _peso_ruolo(use_case: str, tipo_config: str) -> float:
    return PESO_RUOLO.get(use_case, {}).get(tipo_config, 0.0)


def _peso_aspetto(aspetto: Optional[str]) -> float:
    if not aspetto:
        return 1.0
    return PESO_ASPETTO.get(aspetto, 1.0)

# ---------------------------------------------------------------------------
# API: intensità transito (senza fattore natale)
# ---------------------------------------------------------------------------

def calcola_intensita_aspetto(
    use_case: str,
    pianeta_transito: str,
    aspetto_tipo: str,
    orb: float,
    polarita: Optional[float] = None,
    lambda_polarita: float = 0.2,
) -> float:
    """
    Calcola l'intensità di un aspetto transito->natal.

    Parametri:
    - use_case: "daily" | "weekly" | "monthly" | "yearly"
    - pianeta_transito: nome del pianeta di transito (es. "Saturno")
    - aspetto_tipo: "congiunzione", "quadratura", "opposizione", "trigono", ...
    - orb: distanza in gradi dall'aspetto esatto
    - polarita: valore tra -1 e +1 (opzionale, se già calcolato da transiti.py)
    - lambda_polarita: quanto la polarità influenza l'intensità visibile

    Ritorna:
    - intensità (float) da usare per ordinare/prioritizzare i transiti.
    """
    tipo_config = TIPO_CONFIG_ASPETTO
    base_pianeta = _peso_pianeta(use_case, pianeta_transito, tipo_config)
    base_ruolo = _peso_ruolo(use_case, tipo_config)
    base_aspetto = _peso_aspetto(aspetto_tipo)
    f_orb = get_fattore_orb(use_case, orb)

    intensita = base_pianeta * base_ruolo * base_aspetto * f_orb

    if polarita is not None:
        # piccolo boost: transiti più armonici vengono leggermente favoriti
        intensita *= (1.0 + lambda_polarita * polarita)

    return intensita


def calcola_intensita_posizione(
    use_case: str,
    pianeta_transito: str,
    tipo_config: str,
) -> float:
    """
    Calcola l'intensità di una configurazione di 'posizione' del pianeta:
    - transito_pianeta_generale (tipo_config = "generale")
    - transito_pianeta_casa (tipo_config = "casa")

    Non usa l'orb né il tipo di aspetto.
    """
    base_pianeta = _peso_pianeta(use_case, pianeta_transito, tipo_config)
    base_ruolo = _peso_ruolo(use_case, tipo_config)
    return base_pianeta * base_ruolo

# ---------------------------------------------------------------------------
# Fattore natale per pianeta (casa angolare, ruler Asc, n° aspetti stretti)
# ---------------------------------------------------------------------------

CASE_ANGOLARI = {1, 4, 7, 10}


def calcola_fattore_natale_pianeta(
    pianeta_natale: str,
    natal_houses: Optional[Dict[str, int]] = None,
    asc_ruler: Optional[str] = None,
    natal_aspects: Optional[List[Dict]] = None,
    orb_max_aspetti: float = 3.0,
    incremento_per_aspetto: float = 0.05,
    incremento_casa_angolare: float = 0.10,
    incremento_ruler_asc: float = 0.20,
    fattore_max_aspetti: float = 1.5,
) -> float:
    """
    Calcola il fattore di peso natale per un pianeta, secondo le regole:

    + casa angolare => +10%
    + signore dell'ascendente => +20%
    + numero di aspetti orb < 3° nel tema => +5% per aspetto (clippato)

    Ritorna un fattore >= 1.0.
    """
    base = 1.0

    # casa angolare?
    if natal_houses and pianeta_natale in natal_houses:
        casa = natal_houses[pianeta_natale]
        if casa in CASE_ANGOLARI:
            base *= (1.0 + incremento_casa_angolare)

    # ruler dell'Ascendente?
    if asc_ruler and pianeta_natale == asc_ruler:
        base *= (1.0 + incremento_ruler_asc)

    # numero di aspetti stretti nel tema natale
    n_aspetti = 0
    if natal_aspects:
        for asp in natal_aspects:
            p1 = asp.get("pianeta1")
            p2 = asp.get("pianeta2")
            orb = asp.get("orb")
            if not isinstance(orb, (int, float)):
                continue
            if orb <= orb_max_aspetti and (p1 == pianeta_natale or p2 == pianeta_natale):
                n_aspetti += 1

    fattore_aspetti = 1.0 + incremento_per_aspetto * n_aspetti
    if fattore_aspetti > fattore_max_aspetti:
        fattore_aspetti = fattore_max_aspetti

    return base * fattore_aspetti


def costruisci_profilo_natale(
    natal_houses: Dict[str, int],
    asc_ruler: Optional[str],
    natal_aspects: List[Dict],
) -> Dict[str, float]:
    """
    Costruisce un profilo natale:
      { pianeta: fattore_natale }

    Da usare come input in calcola_score_definitivo_aspetto.
    """
    profilo: Dict[str, float] = {}

    # raccogliamo tutti i pianeti che compaiono almeno nelle case
    pianeti = set(natal_houses.keys())
    for a in natal_aspects:
        p1 = a.get("pianeta1")
        p2 = a.get("pianeta2")
        if isinstance(p1, str):
            pianeti.add(p1)
        if isinstance(p2, str):
            pianeti.add(p2)

    for p in pianeti:
        profilo[p] = calcola_fattore_natale_pianeta(
            pianeta_natale=p,
            natal_houses=natal_houses,
            asc_ruler=asc_ruler,
            natal_aspects=natal_aspects,
        )

    return profilo

# ---------------------------------------------------------------------------
# API principale: score definitivo transito (transito * natale)
# ---------------------------------------------------------------------------

def calcola_score_definitivo_aspetto(
    use_case: str,
    pianeta_transito: str,
    pianeta_natale: str,
    aspetto_tipo: str,
    orb: float,
    polarita: Optional[float] = None,
    profilo_natale: Optional[Dict[str, float]] = None,
) -> Dict[str, float]:
    """
    Combina:
    - intensità del transito (pianeta_transito, aspetto, orb, polarità, use_case)
    - fattore natale (casa angolare, ruler Asc, aspetti stretti del pianeta_natale)

    Ritorna un dict:
      {
        "intensita_base": float,
        "fattore_natale": float,
        "score_definitivo": float,
      }
    """
    intensita_base = calcola_intensita_aspetto(
        use_case=use_case,
        pianeta_transito=pianeta_transito,
        aspetto_tipo=aspetto_tipo,
        orb=orb,
        polarita=polarita,
    )

    fattore_natale = 1.0
    if profilo_natale is not None:
        fattore_natale = profilo_natale.get(pianeta_natale, 1.0)

    score_def = intensita_base * fattore_natale

    return {
        "intensita_base": float(intensita_base),
        "fattore_natale": float(fattore_natale),
        "score_definitivo": float(score_def),
    }
