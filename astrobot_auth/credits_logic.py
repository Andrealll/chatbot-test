"""
Shim per esporre astrobot_auth.credits_logic dentro il progetto chatbot-test.

Usa il modulo locale `credits_logic_old.py` che sta nella root del repo.
Su Render verrà caricato insieme al resto del codice, quindi
questo shim funziona sia in locale sia in produzione.

IMPORTANTE:
- Non sposta nulla dal repo astrobot_auth esterno.
- Non richiede sottocartelle tipo astrobot_auth.astrobot_auth.
"""

from astrobot_auth.credits_logic import (
    load_user_credits_state,
    save_user_credits_state,
    decide_premium_mode,
    apply_premium_consumption,
    log_usage_event,
    PremiumDecision,
)
