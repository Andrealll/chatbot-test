# settings_credits.py

import os

def _get_int_env(var_name: str, default: int) -> int:
    value = os.getenv(var_name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        # fallback di sicurezza se la variabile è rotta
        return default

# Numero di tentativi gratuiti per periodo
FREE_TRIES_PER_PERIOD = _get_int_env("ASTROBOT_FREE_TRIES_PER_PERIOD", 2)

# Durata del periodo in giorni (1 = giornaliero, 7 = settimanale, ecc.)
FREE_TRIES_PERIOD_DAYS = _get_int_env("ASTROBOT_FREE_TRIES_PERIOD_DAYS", 1)
