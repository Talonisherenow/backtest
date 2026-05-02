import re


def normalize_symbol(raw: str) -> str:
    value = raw.strip().upper()
    value = value.replace("_", ".")

    if re.fullmatch(r"\d{6}\.(SZ|SH)", value):
        return value

    if re.fullmatch(r"(SZ|SH)\d{6}", value):
        return f"{value[2:]}.{value[:2]}"

    if re.fullmatch(r"\d{6}", value):
        suffix = "SH" if value.startswith(("5", "6", "9")) else "SZ"
        return f"{value}.{suffix}"

    raise ValueError(f"Unsupported A share symbol: {raw}")


def akshare_symbol(symbol: str) -> str:
    return normalize_symbol(symbol).split(".")[0]
