# Data Source HTTP API

Base URL is discovered from the server-side IM agent runtime or explicit user/operator configuration. Complete `access-discovery.md` before using these endpoints.

All requests use:

```text
Authorization: Bearer <configured token>
```

Never print the token in chat.

The API contract is independent of transport. The current server may reach a home/local backtest service through frp, Nginx, localhost forwarding, a private route, or another controlled path; callers should treat only the discovered `base_url` as the contract.

## Read Endpoints

```text
GET /api/health
GET /api/data-sources
GET /api/kline/manifest
GET /api/kline/bars?source_id=<source_id>&symbol=<symbol>&frequency=<frequency>&adjust=<adjust>&limit=<n>&anchor=latest
GET /api/data/tasks?source_id=<source_id>
GET /api/data/inventory?source_id=<source_id>
GET /api/data/jobs
GET /api/data/jobs/<job_id>
```

## Submit Job

```text
POST /api/data/jobs
Content-Type: application/json
```

Body:

```json
{
  "name": "crypto-bitget-core",
  "source": "ccxt",
  "exchange": "bitget",
  "symbols": ["BTC/USDT", "ETH/USDT"],
  "frequencies": ["1d", "4h"],
  "adjust": "none",
  "start_date": "<computed start_date>",
  "end_date": "<computed end_date>",
  "bars_root": "data/crypto/bitget/bars",
  "metadata": "data/crypto/bitget/metadata.sqlite",
  "output_dir": "runs/crypto_market_data/bitget_core",
  "page_delay_seconds": 0.35,
  "retry": {
    "max_attempts": 5,
    "request_delay_seconds": 0.5,
    "failure_cooldown_seconds": 30,
    "continue_on_error": true
  }
}
```

Paths are server-side paths on the data-source machine.

## Retry Failed

```text
POST /api/data/retry-failed
Content-Type: application/json
```

Body:

```json
{"source_id":"bitget"}
```

## Status Meaning

Job status can be `submitted`, `running`, `success`, or `failed`.

Crawl task status can include `pending`, `running`, `retrying`, `success`, or `failed`.
