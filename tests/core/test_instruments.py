from decimal import Decimal

import pytest

from backtest.core.instruments import (
    AssetClass,
    Instrument,
    Market,
    TradingRule,
)


def test_instrument_accepts_a_share_hk_stock_us_stock_and_crypto_ids():
    instruments = [
        Instrument(
            instrument_id="000001.SZ",
            market=Market.A_SHARE,
            exchange="SZSE",
            asset_class=AssetClass.STOCK,
            quote_currency="CNY",
        ),
        Instrument(
            instrument_id="00700.HK",
            market=Market.HK_STOCK,
            exchange="HKEX",
            asset_class=AssetClass.STOCK,
            quote_currency="HKD",
        ),
        Instrument(
            instrument_id="AAPL.US",
            market=Market.US_STOCK,
            exchange="NASDAQ",
            asset_class=AssetClass.STOCK,
            quote_currency="USD",
        ),
        Instrument(
            instrument_id="BTC-USDT.BINANCE",
            market=Market.CRYPTO_SPOT,
            exchange="BINANCE",
            asset_class=AssetClass.CRYPTO,
            quote_currency="USDT",
        ),
    ]

    assert [item.instrument_id for item in instruments] == [
        "000001.SZ",
        "00700.HK",
        "AAPL.US",
        "BTC-USDT.BINANCE",
    ]


def test_trading_rule_rounds_quantity_down_to_lot_size():
    rule = TradingRule(
        instrument_id="00700.HK",
        lot_size=Decimal("100"),
        tick_size=Decimal("0.01"),
        min_order_quantity=Decimal("100"),
        min_order_notional=Decimal("0"),
    )

    assert rule.round_quantity(Decimal("987")) == Decimal("900.00000000")
    assert rule.round_quantity(Decimal("99")) == Decimal("0")


def test_trading_rule_rejects_non_positive_lot_and_tick():
    with pytest.raises(ValueError, match="lot_size"):
        TradingRule(
            instrument_id="AAPL.US",
            lot_size=Decimal("0"),
            tick_size=Decimal("0.01"),
            min_order_quantity=Decimal("1"),
            min_order_notional=Decimal("0"),
        )

    with pytest.raises(ValueError, match="tick_size"):
        TradingRule(
            instrument_id="AAPL.US",
            lot_size=Decimal("1"),
            tick_size=Decimal("0"),
            min_order_quantity=Decimal("1"),
            min_order_notional=Decimal("0"),
        )
