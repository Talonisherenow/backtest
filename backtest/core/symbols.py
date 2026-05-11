import re
from urllib.parse import quote, unquote


def normalize_symbol(raw: str) -> str:
    value = raw.strip().upper()
    value = value.replace("_", ".")

    if re.fullmatch(r"\d{6}\.(SZ|SH|BJ)", value):
        return value

    if re.fullmatch(r"(SZ|SH|BJ)\d{6}", value):
        return f"{value[2:]}.{value[:2]}"

    if re.fullmatch(r"\d{6}", value):
        if value.startswith(("4", "8")):
            suffix = "BJ"
        elif value.startswith(("5", "6", "9")):
            suffix = "SH"
        else:
            suffix = "SZ"
        return f"{value}.{suffix}"

    if re.fullmatch(r"[A-Z0-9]+/[A-Z0-9]+", value):
        return value

    raise ValueError(f"Unsupported symbol: {raw}")


def akshare_symbol(symbol: str) -> str:
    return normalize_symbol(symbol).split(".")[0]


def safe_symbol_path(symbol: str) -> str:
    return quote(normalize_symbol(symbol), safe=".-_")


def symbol_from_safe_path(value: str) -> str:
    return normalize_symbol(unquote(value))
