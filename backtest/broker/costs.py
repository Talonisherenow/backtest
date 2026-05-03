from dataclasses import dataclass


@dataclass(frozen=True)
class TradeCost:
    commission: float
    tax: float

    @property
    def total(self) -> float:
        return self.commission + self.tax


class AShareCostModel:
    def __init__(self, commission_rate: float, min_commission: float, stamp_tax_rate: float) -> None:
        self.commission_rate = commission_rate
        self.min_commission = min_commission
        self.stamp_tax_rate = stamp_tax_rate

    def calculate(self, side: str, value: float) -> TradeCost:
        commission = max(value * self.commission_rate, self.min_commission) if value > 0 else 0.0
        tax = value * self.stamp_tax_rate if side == "sell" else 0.0
        return TradeCost(commission=round(commission, 6), tax=round(tax, 6))
