from dataclasses import dataclass, field


@dataclass
class Lot:
    shares: int
    available_date: object


@dataclass
class Account:
    cash: float
    positions: dict[str, int] = field(default_factory=dict)
    lots: dict[str, list[Lot]] = field(default_factory=dict)

    def shares(self, symbol: str) -> int:
        return self.positions.get(symbol, 0)

    def add_position(self, symbol: str, shares: int, available_date: object) -> None:
        self.positions[symbol] = self.positions.get(symbol, 0) + shares
        self.lots.setdefault(symbol, []).append(Lot(shares=shares, available_date=available_date))

    def available_shares(self, symbol: str, trade_date: object) -> int:
        return sum(lot.shares for lot in self.lots.get(symbol, []) if lot.available_date <= trade_date)

    def remove_available_shares(self, symbol: str, shares: int, trade_date: object) -> None:
        remaining = shares
        for lot in self.lots.get(symbol, []):
            if lot.available_date > trade_date or remaining <= 0:
                continue
            consumed = min(lot.shares, remaining)
            lot.shares -= consumed
            remaining -= consumed
        self.lots[symbol] = [lot for lot in self.lots.get(symbol, []) if lot.shares > 0]
        self.positions[symbol] = self.positions.get(symbol, 0) - shares
