"""
Shim per esporre astrobot_auth.credits_logic anche nel backend chatbot-test.

NON sposta nulla: reimporta semplicemente dal package interno
C:\...\astrobot_auth\astrobot_auth\credits_logic.py
quando il repo completo è presente come sottocartella.
"""

from .astrobot_auth.credits_logic import (
    load_user_credits_state,
    save_user_credits_state,
    decide_premium_mode,
    apply_premium_consumption,
    log_usage_event,
    PremiumDecision,
)
