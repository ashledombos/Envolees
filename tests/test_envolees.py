"""Tests for Envolées."""

import pytest


class TestConfig:
    """Tests for configuration module."""

    def test_config_defaults(self):
        """Test default configuration values."""
        from envolees.config import Config

        cfg = Config()

        assert cfg.start_balance == 100_000.0
        assert cfg.risk_per_trade == 0.0025
        assert cfg.ema_period == 200
        assert cfg.atr_period == 14
        assert cfg.donchian_n == 20
        assert cfg.sl_atr == 1.0
        assert cfg.tp_r == 1.0

    def test_config_from_env(self):
        """Test loading config from environment."""
        from envolees.config import Config

        cfg = Config.from_env()
        assert cfg.start_balance > 0


class TestIndicators:
    """Tests for technical indicators."""

    def test_compute_ema(self):
        """Test EMA calculation."""
        import pandas as pd

        from envolees.indicators import compute_ema

        series = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
        ema = compute_ema(series, period=3)

        assert len(ema) == 5
        assert not ema.isna().all()

    def test_compute_atr(self):
        """Test ATR calculation."""
        import pandas as pd

        from envolees.indicators import compute_atr

        df = pd.DataFrame({
            "High": [10.0, 11.0, 12.0, 11.5, 13.0],
            "Low": [9.0, 9.5, 10.0, 10.0, 11.0],
            "Close": [9.5, 10.5, 11.0, 10.5, 12.0],
        })
        atr = compute_atr(df, period=3)

        assert len(atr) == 5
        # First 2 values should be NaN (min_periods=3)
        assert atr.isna().sum() == 2

    def test_compute_donchian(self):
        """Test Donchian channel calculation."""
        import pandas as pd

        from envolees.indicators import compute_donchian

        df = pd.DataFrame({
            "High": [10.0, 11.0, 12.0, 11.5, 13.0, 14.0],
            "Low": [9.0, 9.5, 10.0, 10.0, 11.0, 12.0],
        })
        d_high, d_low = compute_donchian(df, period=3, shift=1)

        assert len(d_high) == 6
        assert len(d_low) == 6


class TestStrategy:
    """Tests for trading strategy."""

    def test_donchian_strategy_init(self):
        """Test strategy initialization."""
        from envolees.config import Config
        from envolees.strategy import DonchianBreakoutStrategy

        cfg = Config()
        strategy = DonchianBreakoutStrategy(cfg)

        assert strategy.cfg == cfg

    def test_compute_entry_sl_tp_long(self):
        """Test entry/SL/TP calculation for long."""
        from envolees.config import Config
        from envolees.strategy import DonchianBreakoutStrategy
        from envolees.strategy.base import Signal
        import pandas as pd

        cfg = Config(sl_atr=1.0, tp_r=1.0)
        strategy = DonchianBreakoutStrategy(cfg)

        signal = Signal(
            direction="LONG",
            entry_level=100.0,
            atr_at_signal=2.0,
            timestamp=pd.Timestamp.now(),
        )

        entry, sl, tp = strategy.compute_entry_sl_tp(signal, exec_penalty_atr=0.10)

        # Entry = 100 + 0.10 * 2 = 100.2
        assert entry == pytest.approx(100.2)
        # SL = 100.2 - 1.0 * 2 = 98.2
        assert sl == pytest.approx(98.2)
        # Risk = 2.0, TP = 100.2 + 2.0 = 102.2
        assert tp == pytest.approx(102.2)


class TestPosition:
    """Tests for position management."""

    def test_open_position_pnl(self):
        """Test P&L calculation."""
        import pandas as pd

        from envolees.backtest.position import OpenPosition

        pos = OpenPosition(
            direction="LONG",
            entry=100.0,
            sl=98.0,
            tp=102.0,
            ts_signal=pd.Timestamp.now(),
            ts_entry=pd.Timestamp.now(),
            atr_signal=2.0,
            entry_bar_idx=0,
            risk_cash=250.0,
        )

        # Win: exit at TP
        pnl_r = pos.compute_pnl_r(102.0)
        assert pnl_r == pytest.approx(1.0)

        # Loss: exit at SL
        pnl_r = pos.compute_pnl_r(98.0)
        assert pnl_r == pytest.approx(-1.0)

    def test_check_exit_long(self):
        """Test exit detection for long position."""
        import pandas as pd

        from envolees.backtest.position import OpenPosition

        pos = OpenPosition(
            direction="LONG",
            entry=100.0,
            sl=98.0,
            tp=102.0,
            ts_signal=pd.Timestamp.now(),
            ts_entry=pd.Timestamp.now(),
            atr_signal=2.0,
            entry_bar_idx=0,
            risk_cash=250.0,
        )

        # No exit
        reason, price = pos.check_exit(high=101.0, low=99.0)
        assert reason is None

        # SL hit
        reason, price = pos.check_exit(high=101.0, low=97.0)
        assert reason == "SL"
        assert price == 98.0

        # TP hit
        reason, price = pos.check_exit(high=103.0, low=99.0)
        assert reason == "TP"
        assert price == 102.0

        # Both hit (conservative = SL)
        reason, price = pos.check_exit(high=103.0, low=97.0, conservative_same_bar=True)
        assert reason == "SL"
