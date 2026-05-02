from enum import StrEnum


class Frequency(StrEnum):
    DAILY = "1d"
    MIN_1 = "1m"
    MIN_5 = "5m"
    MIN_15 = "15m"
    MIN_30 = "30m"
    MIN_60 = "60m"


class AdjustMode(StrEnum):
    NONE = "none"
    QFQ = "qfq"
    HFQ = "hfq"


class ExecutionTiming(StrEnum):
    NEXT_OPEN = "next_open"
    SAME_CLOSE = "same_close"
    NEXT_CLOSE = "next_close"


class OrderSide(StrEnum):
    BUY = "buy"
    SELL = "sell"


class OrderStatus(StrEnum):
    FILLED = "filled"
    REJECTED = "rejected"
    ADJUSTED = "adjusted"


class MetricResultKind(StrEnum):
    SCALAR = "scalar"
    SERIES = "series"
    TABLE = "table"
