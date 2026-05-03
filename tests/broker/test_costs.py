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


def test_cost_model_applies_transfer_fee_to_buy_and_sell():
    model = AShareCostModel(
        commission_rate=0.0003,
        min_commission=5,
        stamp_tax_rate=0.0005,
        transfer_fee_rate=0.00001,
    )

    buy_cost = model.calculate(side="buy", value=100000)
    sell_cost = model.calculate(side="sell", value=100000)

    assert buy_cost.commission == 30
    assert buy_cost.tax == 0
    assert buy_cost.transfer_fee == 1
    assert buy_cost.total == 31
    assert sell_cost.commission == 30
    assert sell_cost.tax == 50
    assert sell_cost.transfer_fee == 1
    assert sell_cost.total == 81


def test_fixed_slippage_adjusts_buy_and_sell_prices():
    model = FixedRateSlippageModel(rate=0.001)

    assert model.apply("buy", 10.0) == 10.01
    assert model.apply("sell", 10.0) == 9.99
