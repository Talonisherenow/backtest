import pandas as pd
import pytest

from backtest.data.universe import (
    UNIVERSE_COLUMNS,
    normalize_a_share_universe,
    sample_universe_symbols,
)


def test_normalize_a_share_universe_combines_all_a_share_boards():
    sh_main = pd.DataFrame(
        {
            "证券代码": ["600000"],
            "证券简称": ["浦发银行"],
            "上市日期": ["1999-11-10"],
        }
    )
    sh_star = pd.DataFrame(
        {
            "证券代码": ["688001"],
            "证券简称": ["华兴源创"],
            "上市日期": ["2019-07-22"],
        }
    )
    sz_all = pd.DataFrame(
        {
            "板块": ["主板", "创业板"],
            "A股代码": ["000001", "300001"],
            "A股简称": ["平安银行", "特锐德"],
            "A股上市日期": ["1991-04-03", "2009-10-30"],
            "所属行业": ["J 金融业", "C 制造业"],
        }
    )
    bj_all = pd.DataFrame(
        {
            "证券代码": ["430017"],
            "证券简称": ["星昊医药"],
            "上市日期": ["2023-06-20"],
            "所属行业": ["医药制造业"],
        }
    )

    result = normalize_a_share_universe(sh_main, sh_star, sz_all, bj_all)

    assert list(result.columns) == UNIVERSE_COLUMNS
    assert result["symbol"].tolist() == [
        "600000.SH",
        "688001.SH",
        "000001.SZ",
        "300001.SZ",
        "430017.BJ",
    ]
    assert result["board"].tolist() == ["主板", "科创板", "主板", "创业板", "北交所"]
    assert result.loc[result["symbol"] == "300001.SZ", "industry"].item() == "C 制造业"


def test_sample_universe_symbols_is_deterministic():
    universe = pd.DataFrame(
        {
            "symbol": ["600000.SH", "000001.SZ", "300001.SZ", "688001.SH", "430017.BJ"],
        }
    )

    first = sample_universe_symbols(universe, size=3, seed=42)
    second = sample_universe_symbols(universe, size=3, seed=42)

    assert first == second
    assert len(first) == 3
    assert set(first).issubset(set(universe["symbol"]))


def test_normalize_a_share_universe_tolerates_missing_industry_columns():
    sh_main = pd.DataFrame({"证券代码": ["600000"], "证券简称": ["浦发银行"], "上市日期": ["1999-11-10"]})
    sh_star = pd.DataFrame({"证券代码": ["688001"], "证券简称": ["华兴源创"], "上市日期": ["2019-07-22"]})
    sz_all = pd.DataFrame(
        {
            "板块": ["主板"],
            "A股代码": ["000001"],
            "A股简称": ["平安银行"],
            "A股上市日期": ["1991-04-03"],
        }
    )
    bj_all = pd.DataFrame({"证券代码": ["430017"], "证券简称": ["星昊医药"], "上市日期": ["2023-06-20"]})

    result = normalize_a_share_universe(sh_main, sh_star, sz_all, bj_all)

    assert result.loc[result["symbol"] == "000001.SZ", "industry"].item() == ""
    assert result.loc[result["symbol"] == "430017.BJ", "industry"].item() == ""


def test_sample_universe_symbols_rejects_oversized_requests():
    universe = pd.DataFrame({"symbol": ["600000.SH"]})

    with pytest.raises(ValueError, match="sample size"):
        sample_universe_symbols(universe, size=2, seed=42)
