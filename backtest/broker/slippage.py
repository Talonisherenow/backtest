class FixedRateSlippageModel:
    def __init__(self, rate: float) -> None:
        self.rate = rate

    def apply(self, side: str, price: float) -> float:
        if side == "buy":
            return round(price * (1 + self.rate), 6)
        if side == "sell":
            return round(price * (1 - self.rate), 6)
        raise ValueError(f"Unsupported side: {side}")
