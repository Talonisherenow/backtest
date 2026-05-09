# Crypto Market Data Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add CCXT-based crypto spot OHLCV ingestion while preserving the existing A-share data and backtest behavior.

**Architecture:** Keep the current `DataProvider -> DataSyncService -> ParquetBarStore -> DataCatalog` path. Extend the core symbol/frequency contracts just enough for crypto spot pairs, add a focused `CCXTOHLCVProvider`, wire `source=ccxt` through the data CLI, and document that this is historical market data only, not live trading or a complete crypto broker.

**Tech Stack:** Python 3.11+, pandas, pydantic v2, Typer, pytest, Parquet/pyarrow, CCXT.

---

## Scope

Implement:

- `source: ccxt` historical OHLCV ingestion.
- Config field `data.exchange` for the CCXT exchange id.
- Crypto spot symbols like `BTC/USDT`.
- Frequency `4h`.
- Internal-to-CCXT timeframe mapping, including `60m -> 1h`.
- Safe cache partition paths for symbols containing `/`.
- Documentation and AI handoff updates.

Do not implement:

- Live order placement.
- Credentials or API key handling.
- Futures/perpetuals symbols.
- Crypto-specific broker simulation.
- WebSocket or realtime data.

## File Structure

Create:

- `backtest/data/ccxt_provider.py`: CCXT OHLCV provider and timeframe mapping.
- `tests/data/test_ccxt_provider.py`: fake-exchange tests for CCXT behavior.
- `docs/superpowers/specs/2026-05-08-crypto-market-data-design.md`: design doc.
- `docs/superpowers/plans/2026-05-08-crypto-market-data.md`: this implementation plan.

Modify:

- `pyproject.toml`: add `ccxt` dependency.
- `backtest/core/enums.py`: add `Frequency.HOUR_4 = "4h"`.
- `backtest/core/symbols.py`: allow simple crypto spot symbols and add safe path helpers.
- `backtest/core/frames.py`: continue using `normalize_symbol()` so BarFrame accepts crypto pairs.
- `backtest/config/models.py`: add optional `DataConfig.exchange`.
- `backtest/data/store.py`: encode symbol values in partition paths and include full end-date for intraday reads.
- `backtest/data/service.py`: normalize crypto symbols through the updated normalizer.
- `backtest/cli/data.py`: choose AkShare or CCXT provider and use `ccxt:<exchange>` catalog source.
- `docs/data-contracts.md`: document crypto symbols, `4h`, and crypto BarFrame conventions.
- `docs/data-ingestion.md`: document `source=ccxt` sync.
- `docs/cli.md`: document crypto data sync config.
- `docs/ai-handoff.md`: update current branch, capability, limits, and verification notes.

## Task 1: Core Crypto Symbol, Frequency, And Store Support

**Files:**

- Modify: `backtest/core/enums.py`
- Modify: `backtest/core/symbols.py`
- Modify: `backtest/data/store.py`
- Test: `tests/core/test_symbols.py`
- Test: `tests/core/test_frames.py`
- Test: `tests/data/test_store.py`

- [ ] **Step 1: Write failing tests**

Add tests that assert:

```python
from backtest.core.symbols import normalize_symbol, safe_symbol_path, symbol_from_safe_path


def test_normalize_symbol_accepts_crypto_spot_pair():
    assert normalize_symbol("btc/usdt") == "BTC/USDT"


def test_normalize_symbol_rejects_contract_style_crypto_pair():
    with pytest.raises(ValueError, match="Unsupported symbol"):
        normalize_symbol("BTC/USDT:USDT")


def test_crypto_symbol_path_round_trip():
    encoded = safe_symbol_path("BTC/USDT")

    assert encoded == "BTC%2FUSDT"
    assert symbol_from_safe_path(encoded) == "BTC/USDT"
```

Add a BarFrame test that `validate_bar_frame()` accepts `BTC/USDT`, `frequency="4h"`, and `adjust="none"`.

Add a store test that writes `BTC/USDT` intraday bars and verifies:

```python
path.parts includes "symbol=BTC%2FUSDT"
read_bars(..., end_date=that_date) returns all intraday rows for that date
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
.venv/bin/python -m pytest tests/core/test_symbols.py tests/core/test_frames.py tests/data/test_store.py -q
```

Expected: fail because `4h`, crypto symbols, and safe path helpers do not exist.

- [ ] **Step 3: Implement minimal core support**

Implementation requirements:

- Add `Frequency.HOUR_4 = "4h"`.
- Update `normalize_symbol()` to accept A-share formats and simple `BASE/QUOTE` crypto pairs.
- Change invalid symbol message to `Unsupported symbol: <raw>`.
- Add `safe_symbol_path()` and `symbol_from_safe_path()` using URL percent encoding.
- Use `safe_symbol_path()` in `ParquetBarStore.partition_path()`.
- In `ParquetBarStore.read_bars()`, normalize requested symbols and include the whole `end_date` day with an exclusive `< end_date + 1 day` comparison.

- [ ] **Step 4: Run tests and verify GREEN**

Run:

```bash
.venv/bin/python -m pytest tests/core/test_symbols.py tests/core/test_frames.py tests/data/test_store.py -q
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add backtest/core/enums.py backtest/core/symbols.py backtest/data/store.py tests/core/test_symbols.py tests/core/test_frames.py tests/data/test_store.py
git commit -m "feat: support crypto symbols in market data cache"
```

## Task 2: CCXT OHLCV Provider

**Files:**

- Create: `backtest/data/ccxt_provider.py`
- Modify: `pyproject.toml`
- Test: `tests/data/test_ccxt_provider.py`

- [ ] **Step 1: Write failing provider tests**

Create fake exchange tests for:

- successful `BTC/USDT` 4h fetch.
- `Frequency.MIN_60` maps to CCXT `1h`.
- pagination advances by timeframe duration.
- current incomplete candle is dropped.
- `adjust != none` raises `ValueError`.
- exchange without `fetchOHLCV` raises `ValueError`.
- missing symbol raises `ValueError`.
- unsupported timeframe raises `ValueError`.

The fake exchange should expose:

```python
has = {"fetchOHLCV": True}
timeframes = {"1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m", "1h": "1h", "4h": "4h", "1d": "1d"}
markets = {"BTC/USDT": {}}
load_markets()
fetch_ohlcv(symbol, timeframe="1m", since=None, limit=None, params=None)
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
.venv/bin/python -m pytest tests/data/test_ccxt_provider.py -q
```

Expected: fail because `backtest.data.ccxt_provider` does not exist.

- [ ] **Step 3: Implement provider**

Implementation requirements:

- `CCXTOHLCVProvider(exchange_id="binance", exchange=None, limit=1000, drop_incomplete=True, now_ms=None)`.
- Lazy import `ccxt` only when no fake exchange is injected.
- Create exchange with `{"enableRateLimit": True}`.
- Map internal timeframes:

```python
{
    Frequency.MIN_1: "1m",
    Frequency.MIN_5: "5m",
    Frequency.MIN_15: "15m",
    Frequency.MIN_30: "30m",
    Frequency.MIN_60: "1h",
    Frequency.HOUR_4: "4h",
    Frequency.DAILY: "1d",
}
```

- Reject non-`none` adjust.
- Convert CCXT rows `[timestamp_ms, open, high, low, close, volume]` to `BarFrame`.
- Use UTC timestamps and store timezone-naive datetimes.
- Estimate `amount` as `close * volume`.
- Drop incomplete current candle when `timestamp + timeframe_ms > now_ms`.
- Return `validate_bar_frame(...)`.

- [ ] **Step 4: Run tests and verify GREEN**

Run:

```bash
.venv/bin/python -m pytest tests/data/test_ccxt_provider.py -q
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml backtest/data/ccxt_provider.py tests/data/test_ccxt_provider.py
git commit -m "feat: add ccxt crypto ohlcv provider"
```

## Task 3: CLI And Config Wiring

**Files:**

- Modify: `backtest/config/models.py`
- Modify: `backtest/cli/data.py`
- Test: `tests/config/test_config_loader.py`
- Test: `tests/test_cli_commands.py`

- [ ] **Step 1: Write failing tests**

Add config loader coverage for:

```yaml
data:
  source: ccxt
  exchange: binance
  frequency: 4h
  adjust: none
  stock_pool:
    symbols:
      - BTC/USDT
```

Add CLI tests asserting:

- `data sync` with `source=ccxt` creates `CCXTOHLCVProvider(exchange_id="binance")`.
- sync kwargs use `source="ccxt:binance"`.
- `data coverage` with the same config checks `source="ccxt:binance"`.
- `source=ccxt` without `exchange` exits with a clear message.
- unknown data source still exits with a clear message.

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
.venv/bin/python -m pytest tests/config/test_config_loader.py tests/test_cli_commands.py -q
```

Expected: fail because `DataConfig.exchange` and CCXT CLI provider selection do not exist.

- [ ] **Step 3: Implement wiring**

Implementation requirements:

- Add `exchange: str | None = None` to `DataConfig`.
- Normalize non-empty exchange ids to lowercase/trimmed.
- In `backtest/cli/data.py`, add helper `_provider_for_config(config)`:

```python
if config.data.source == "akshare": return AkShareProvider()
if config.data.source == "ccxt": require config.data.exchange; return CCXTOHLCVProvider(exchange_id=config.data.exchange)
raise typer.BadParameter(...)
```

- Add helper `_catalog_source(config)`:

```python
"akshare" for AkShare
f"ccxt:{exchange}" for CCXT
```

- Use `_catalog_source(config)` in sync and coverage.

- [ ] **Step 4: Run tests and verify GREEN**

Run:

```bash
.venv/bin/python -m pytest tests/config/test_config_loader.py tests/test_cli_commands.py -q
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add backtest/config/models.py backtest/cli/data.py tests/config/test_config_loader.py tests/test_cli_commands.py
git commit -m "feat: wire ccxt market data sync"
```

## Task 4: Documentation And AI Handoff

**Files:**

- Modify: `docs/data-contracts.md`
- Modify: `docs/data-ingestion.md`
- Modify: `docs/cli.md`
- Modify: `docs/ai-handoff.md`

- [ ] **Step 1: Update docs**

Document:

- `source=ccxt` and `exchange`.
- Supported crypto timeframes and recommended defaults.
- `adjust=none`.
- `BTC/USDT` cache path encoding.
- `amount=close * volume` estimate.
- Historical data only; no live trading or crypto broker yet.
- Full verification command and current branch.

- [ ] **Step 2: Run docs checks**

Run:

```bash
git diff --check -- docs/data-contracts.md docs/data-ingestion.md docs/cli.md docs/ai-handoff.md
```

Expected: no output.

- [ ] **Step 3: Commit**

```bash
git add docs/data-contracts.md docs/data-ingestion.md docs/cli.md docs/ai-handoff.md
git commit -m "docs: document crypto market data ingestion"
```

## Task 5: Final Verification

**Files:** all touched files.

- [ ] **Step 1: Install updated dependencies**

Run:

```bash
.venv/bin/python -m pip install -e ".[dev]"
```

Expected: installation succeeds and `ccxt` is importable.

- [ ] **Step 2: Run targeted tests**

Run:

```bash
.venv/bin/python -m pytest tests/core/test_symbols.py tests/core/test_frames.py tests/data/test_store.py tests/data/test_ccxt_provider.py tests/config/test_config_loader.py tests/test_cli_commands.py -q
```

Expected: all targeted tests pass.

- [ ] **Step 3: Run full suite**

Run:

```bash
.venv/bin/python -m pytest -q
```

Expected: full suite passes.

- [ ] **Step 4: Check final diff**

Run:

```bash
git status --short --branch
git diff --check
```

Expected: only intended tracked changes or clean working tree after commits; untracked chart exports may remain untouched.

