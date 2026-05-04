from __future__ import annotations

import akshare as ak
import pandas as pd

UNIVERSE_COLUMNS = ["symbol", "code", "name", "exchange", "board", "list_date", "industry"]


class AkShareUniverseProvider:
    def fetch_a_share_universe(self) -> pd.DataFrame:
        sh_main = ak.stock_info_sh_name_code(symbol="主板A股")
        sh_star = ak.stock_info_sh_name_code(symbol="科创板")
        sz_all = ak.stock_info_sz_name_code(symbol="A股列表")
        bj_all = ak.stock_info_bj_name_code()
        return normalize_a_share_universe(sh_main, sh_star, sz_all, bj_all)


def normalize_a_share_universe(
    sh_main: pd.DataFrame,
    sh_star: pd.DataFrame,
    sz_all: pd.DataFrame,
    bj_all: pd.DataFrame,
) -> pd.DataFrame:
    frames = [
        _normalize_sh(sh_main, board="主板"),
        _normalize_sh(sh_star, board="科创板"),
        _normalize_sz(sz_all),
        _normalize_bj(bj_all),
    ]
    result = pd.concat(frames, ignore_index=True)
    result = result.drop_duplicates(subset=["symbol"], keep="first")
    return result[UNIVERSE_COLUMNS].reset_index(drop=True)


def sample_universe_symbols(universe: pd.DataFrame, size: int, seed: int | None = None) -> list[str]:
    if size <= 0:
        raise ValueError("sample size must be positive")
    if "symbol" not in universe.columns:
        raise ValueError("universe file must contain a symbol column")

    symbols = universe["symbol"].dropna().astype(str).drop_duplicates().reset_index(drop=True)
    if size > len(symbols):
        raise ValueError(f"sample size {size} exceeds universe size {len(symbols)}")

    return symbols.sample(n=size, random_state=seed).tolist()


def _normalize_sh(frame: pd.DataFrame, board: str) -> pd.DataFrame:
    code = _as_code(frame["证券代码"])
    return pd.DataFrame(
        {
            "symbol": code + ".SH",
            "code": code,
            "name": frame["证券简称"].astype(str),
            "exchange": "SH",
            "board": board,
            "list_date": frame["上市日期"].astype(str),
            "industry": "",
        }
    )


def _normalize_sz(frame: pd.DataFrame) -> pd.DataFrame:
    code = _as_code(frame["A股代码"])
    return pd.DataFrame(
        {
            "symbol": code + ".SZ",
            "code": code,
            "name": frame["A股简称"].astype(str),
            "exchange": "SZ",
            "board": frame["板块"].astype(str),
            "list_date": frame["A股上市日期"].astype(str),
            "industry": _optional_text_column(frame, "所属行业"),
        }
    )


def _normalize_bj(frame: pd.DataFrame) -> pd.DataFrame:
    code = _as_code(frame["证券代码"])
    return pd.DataFrame(
        {
            "symbol": code + ".BJ",
            "code": code,
            "name": frame["证券简称"].astype(str),
            "exchange": "BJ",
            "board": "北交所",
            "list_date": frame["上市日期"].astype(str),
            "industry": _optional_text_column(frame, "所属行业"),
        }
    )


def _as_code(series: pd.Series) -> pd.Series:
    return series.astype(str).str.strip().str.zfill(6)


def _optional_text_column(frame: pd.DataFrame, name: str) -> pd.Series:
    if name not in frame.columns:
        return pd.Series([""] * len(frame), index=frame.index)
    return frame[name].astype(str)
