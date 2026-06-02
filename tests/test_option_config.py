"""Session 16 config defaults for the options layer."""

from __future__ import annotations

from src.core.config import Settings


def test_options_config_defaults() -> None:
    s = Settings()
    assert s.trade_instrument == "both"
    assert s.enable_options is True
    assert s.option_target_delta == 0.60
    assert s.option_target_dte == 45
    assert s.option_min_dte_exit == 21
    assert s.option_tp_pct == 50.0
    assert s.option_sl_pct == 50.0
    assert s.option_structure == "long_call"
    assert s.risk_free_rate == 0.04
    assert s.option_iv_premium_mult == 1.1
    assert s.realized_vol_window == 20
    assert s.option_slippage_bps_model == 50.0
    assert s.option_chain_min_oi == 10
    assert s.option_multiplier == 100
