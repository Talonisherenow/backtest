from backtest.broker.costs import AShareCostModel
from backtest.broker.slippage import FixedRateSlippageModel


def test_cost_model_applies_min_commission_and_sell_stamp_tax():
    model = AShareCostModel(commission_rate=0.0003, min_commission=5, stamp_tax_rate=0.0005)

    buy_cost = model.calculate(side="buy", value=1000)
    sell_cost = model.calculate(side="sell", value=1000)

    assert buy_cost.commission == 5
    assert buy_cost.tax == 0
    assert sell_cost.commission == 5
    assert sell_cost.tax == 0.5


def test_fixed_slippage_adjusts_buy_and_sell_prices():
    model = FixedRateSlippageModel(rate=0.001)

    assert model.apply("buy", 10.0) == 10.01
    assert model.apply("sell", 10.0) == 9.99
