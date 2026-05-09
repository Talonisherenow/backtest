import pytest

from backtest.core.symbols import normalize_symbol, safe_symbol_path, symbol_from_safe_path


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("000001", "000001.SZ"),
        ("sz000001", "000001.SZ"),
        ("000001.sz", "000001.SZ"),
        ("600519", "600519.SH"),
        ("sh600519", "600519.SH"),
        ("600519.SH", "600519.SH"),
        ("430017", "430017.BJ"),
        ("bj430017", "430017.BJ"),
        ("430017.bj", "430017.BJ"),
        ("873693", "873693.BJ"),
    ],
)
def test_normalize_symbol_accepts_common_a_share_forms(raw, expected):
    assert normalize_symbol(raw) == expected


def test_normalize_symbol_rejects_invalid_code():
    with pytest.raises(ValueError, match="Unsupported symbol"):
        normalize_symbol("ABC123")


def test_normalize_symbol_accepts_crypto_spot_pair():
    assert normalize_symbol("btc/usdt") == "BTC/USDT"


def test_normalize_symbol_rejects_contract_style_crypto_pair():
    with pytest.raises(ValueError, match="Unsupported symbol"):
        normalize_symbol("BTC/USDT:USDT")


def test_crypto_symbol_path_round_trip():
    encoded = safe_symbol_path("BTC/USDT")

    assert encoded == "BTC%2FUSDT"
    assert symbol_from_safe_path(encoded) == "BTC/USDT"
