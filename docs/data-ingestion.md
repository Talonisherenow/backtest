# Data Ingestion

## Components

- `AkShareProvider` fetches daily A-share bars from AkShare.
- `AkShareUniverseProvider` fetches the current all-board A-share stock
  universe from AkShare stock-list endpoints.
- `DataSyncService` coordinates retries, missing range detection, provider
  fetches, store writes, catalog updates, and task status updates.
- `ParquetBarStore` writes validated bars to partitioned Parquet files.
- `MetadataStore` owns the SQLite schema.
- `DataCatalog` records cached coverage and file paths.
- `CrawlTaskManager` records crawl attempts and retry state.

## Cache Layout

Bars are stored under the configured `--bars-root`, partitioned as:

```text
data/bars/
  frequency=1d/
    adjust=qfq/
      symbol=000001.SZ/
        year=2025/
          bars.parquet
```

`ParquetBarStore.write_bars()` validates input, groups by symbol, frequency,
adjust mode, and year, merges with an existing partition if present, drops
duplicate `date + symbol` rows keeping the latest row, sorts by symbol/date, and
atomically replaces the partition file.

## A-share Universe

The project can build a current all-board A-share universe before choosing
which stocks to sync or backtest:

```bash
backtest data universe --output data/universe/a_share_all.csv
```

The AkShare universe provider combines these stock-list endpoints:

- `stock_info_sh_name_code(symbol="主板A股")` for Shanghai main-board A shares.
- `stock_info_sh_name_code(symbol="科创板")` for STAR Market shares.
- `stock_info_sz_name_code(symbol="A股列表")` for Shenzhen main-board and
  ChiNext shares.
- `stock_info_bj_name_code()` for Beijing Stock Exchange shares.

The normalized CSV columns are:

```text
symbol, code, name, exchange, board, list_date, industry
```

`symbol` is the project-wide normalized code, including `.SH`, `.SZ`, and `.BJ`.

For a repeatable random stock batch, sample from the generated universe:

```bash
backtest data sample-pool \
  --universe data/universe/a_share_all.csv \
  --size 200 \
  --seed 42 \
  --output data/universe/sample_200_seed_42.txt
```

The sample output is a one-symbol-per-line file. Use it directly in a backtest
config with:

```yaml
data:
  stock_pool:
    symbols_file: data/universe/sample_200_seed_42.txt
```

## SQLite Metadata

The metadata database defaults to `data/metadata.sqlite`.

`catalog` rows track:

```text
symbol, frequency, adjust, start_date, end_date, rows, source, cache_path,
updated_at, quality_status
```

The primary key is `symbol + frequency + adjust + source + start_date +
end_date + cache_path`. A single Parquet partition can therefore have multiple
catalog coverage rows when observed dates are sparse or when multiple providers
write the same symbol/frequency/adjust partition. Coverage checks can also
filter by `source`, so data cached from one provider does not hide missing
ranges for another provider.

`crawl_tasks` rows track:

```text
task_id, symbol, frequency, adjust, start_date, end_date, source, status,
attempts, last_error, created_at, updated_at, started_at, finished_at
```

Task statuses used by the current task manager are `pending`, `running`,
`success`, `failed`, and `retrying`. The design reserves `cancelled` as a
future lifecycle state, but the current code does not expose a cancellation
command or helper yet.

## Sync Behavior

The command examples use `configs/demo.yaml` as a conventional path. Create that
config first or replace it with your own config file.

Run coverage first when you want to inspect missing ranges:

```bash
backtest data coverage --config configs/demo.yaml --metadata data/metadata.sqlite
```

Run sync to fetch missing data:

```bash
backtest data sync --config configs/demo.yaml --metadata data/metadata.sqlite --bars-root data/bars
```

Sync flow:

1. Normalize symbols from the config stock pool.
2. Execute matching `retrying` tasks first.
3. Ask source-aware `DataCatalog.missing_ranges()` for uncovered date ranges.
4. Create one crawl task per missing symbol/range.
5. Fetch with the configured provider.
6. Validate and write bars to Parquet.
7. Upsert catalog records for observed coverage segments in written partitions.
8. Mark task `success` or `failed`; empty provider results fail the task.

Use `backtest data retry --failed --metadata data/metadata.sqlite` to mark
failed tasks for retry on the next matching sync.

## Provider Notes

The MVP supports `source: akshare` in `backtest data sync`. `AkShareProvider`
accepts only `frequency: 1d`; other frequencies are reserved by the contract for
future providers.
