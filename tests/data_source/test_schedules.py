from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from backtest.data_source.config import DataSourceServerConfig, DataSourceSpec
from backtest.data_source.schedules import (
    DataScheduleConfig,
    DataSourceScheduleService,
    DataSourceScheduleStore,
    DataSourceScheduler,
    build_job_payload,
    compute_next_run_at,
)


def _server_config(tmp_path: Path) -> DataSourceServerConfig:
    bitget_root = tmp_path / "bitget" / "bars"
    a_share_root = tmp_path / "a_share" / "bars"
    bitget_root.mkdir(parents=True)
    a_share_root.mkdir(parents=True)
    return DataSourceServerConfig(
        sources=[
            DataSourceSpec(
                source_id="bitget",
                source_label="Bitget",
                asset_class="crypto",
                bars_root=bitget_root,
                metadata_path=tmp_path / "bitget" / "metadata.sqlite",
                adjust="none",
                catalog_source="ccxt:bitget",
            ),
            DataSourceSpec(
                source_id="a_share",
                source_label="A-share",
                asset_class="equity",
                bars_root=a_share_root,
                metadata_path=tmp_path / "a_share" / "metadata.sqlite",
                adjust="qfq",
                catalog_source="akshare",
            ),
        ]
    )


def _schedule_payload(**overrides):
    payload = {
        "name": "bitget-hourly",
        "enabled": True,
        "trigger": {
            "type": "interval",
            "every": 1,
            "unit": "hours",
            "start_at": "2026-05-18T09:00:00+08:00",
            "timezone": "Asia/Shanghai",
        },
        "repeat": {"mode": "count", "count": 2},
        "job": {
            "source_id": "bitget",
            "symbols": ["BTC/USDT"],
            "frequencies": ["1h"],
            "date_range": {"type": "last_n_days", "days": 7},
        },
    }
    payload.update(overrides)
    return payload


def test_interval_schedule_defaults_to_disabled_and_computes_next_run():
    schedule = DataScheduleConfig.model_validate(
        {
            "name": "bitget-hourly",
            "trigger": {
                "type": "interval",
                "every": 1,
                "unit": "hours",
                "start_at": "2026-05-18T09:00:00+08:00",
                "timezone": "Asia/Shanghai",
            },
            "repeat": {"mode": "count", "count": 3},
            "job": {
                "source_id": "bitget",
                "symbols": ["BTC/USDT"],
                "frequencies": ["1h"],
                "date_range": {"type": "last_n_days", "days": 7},
            },
        }
    )

    next_run = compute_next_run_at(
        schedule,
        now=datetime.fromisoformat("2026-05-18T08:00:00+08:00"),
        run_count=0,
    )

    assert schedule.enabled is False
    assert schedule.overlap_policy == "skip"
    assert next_run is not None
    assert next_run.isoformat() == "2026-05-18T09:00:00+08:00"


def test_repeat_count_exhaustion_has_no_next_run():
    schedule = DataScheduleConfig.model_validate(_schedule_payload())

    assert (
        compute_next_run_at(
            schedule,
            now=datetime.fromisoformat("2026-05-18T10:00:00+08:00"),
            run_count=2,
        )
        is None
    )


def test_daily_and_weekly_triggers_use_local_wall_clock_time():
    daily = DataScheduleConfig.model_validate(
        _schedule_payload(
            trigger={
                "type": "daily",
                "time": "08:30",
                "timezone": "Asia/Shanghai",
            },
            repeat={"mode": "forever"},
        )
    )
    weekly = DataScheduleConfig.model_validate(
        _schedule_payload(
            trigger={
                "type": "weekly",
                "days_of_week": ["mon", "wed"],
                "time": "08:30",
                "timezone": "Asia/Shanghai",
            },
            repeat={"mode": "forever"},
        )
    )

    assert (
        compute_next_run_at(
            daily,
            now=datetime.fromisoformat("2026-05-18T09:00:00+08:00"),
            run_count=0,
        ).isoformat()
        == "2026-05-19T08:30:00+08:00"
    )
    assert (
        compute_next_run_at(
            weekly,
            now=datetime.fromisoformat("2026-05-18T09:00:00+08:00"),
            run_count=0,
        ).isoformat()
        == "2026-05-20T08:30:00+08:00"
    )


def test_daily_trigger_starts_at_first_wall_clock_after_start_at():
    schedule = DataScheduleConfig.model_validate(
        _schedule_payload(
            trigger={
                "type": "daily",
                "time": "08:30",
                "timezone": "Asia/Shanghai",
                "start_at": "2026-05-20T00:00:00+08:00",
            },
            repeat={"mode": "forever"},
        )
    )

    assert (
        compute_next_run_at(
            schedule,
            now=datetime.fromisoformat("2026-05-18T09:00:00+08:00"),
            run_count=0,
        ).isoformat()
        == "2026-05-20T08:30:00+08:00"
    )


def test_weekly_trigger_starts_at_first_wall_clock_after_start_at():
    schedule = DataScheduleConfig.model_validate(
        _schedule_payload(
            trigger={
                "type": "weekly",
                "days_of_week": ["wed"],
                "time": "08:30",
                "timezone": "Asia/Shanghai",
                "start_at": "2026-05-21T00:00:00+08:00",
            },
            repeat={"mode": "forever"},
        )
    )

    assert (
        compute_next_run_at(
            schedule,
            now=datetime.fromisoformat("2026-05-18T09:00:00+08:00"),
            run_count=0,
        ).isoformat()
        == "2026-05-27T08:30:00+08:00"
    )


def test_wall_clock_start_at_is_not_skipped_after_manual_run_before_start():
    schedule = DataScheduleConfig.model_validate(
        _schedule_payload(
            trigger={
                "type": "daily",
                "time": "08:30",
                "timezone": "Asia/Shanghai",
                "start_at": "2026-05-20T08:30:00+08:00",
            },
            repeat={"mode": "forever"},
        )
    )

    assert (
        compute_next_run_at(
            schedule,
            now=datetime.fromisoformat("2026-05-18T09:00:00+08:00"),
            run_count=1,
            after=True,
        ).isoformat()
        == "2026-05-20T08:30:00+08:00"
    )


def test_job_template_compiles_to_existing_data_job_payload(tmp_path: Path):
    schedule = DataScheduleConfig.model_validate(
        _schedule_payload(
            name="bitget-refresh",
            trigger={"type": "once", "run_at": "2026-05-18T09:00:00+08:00"},
            job={
                "source_id": "bitget",
                "symbols": ["BTC/USDT"],
                "frequencies": ["1d", "1h"],
                "date_range": {"type": "last_n_days", "days": 7, "end_offset_days": 1},
                "page_delay_seconds": 0.35,
                "retry": {"max_attempts": 5},
            },
        )
    )

    payload = build_job_payload(
        schedule,
        _server_config(tmp_path),
        now=datetime.fromisoformat("2026-05-18T12:00:00+08:00"),
    )

    assert payload["name"] == "scheduled-bitget-refresh"
    assert payload["source"] == "ccxt"
    assert payload["exchange"] == "bitget"
    assert payload["symbols"] == ["BTC/USDT"]
    assert payload["frequencies"] == ["1d", "1h"]
    assert payload["adjust"] == "none"
    assert payload["start_date"] == "2026-05-11"
    assert payload["end_date"] == "2026-05-17"
    assert payload["bars_root"] == str(tmp_path / "bitget" / "bars")
    assert payload["metadata"] == str(tmp_path / "bitget" / "metadata.sqlite")
    assert payload["page_delay_seconds"] == 0.35
    assert payload["retry"]["max_attempts"] == 5


def test_job_template_compiles_a_share_defaults(tmp_path: Path):
    schedule = DataScheduleConfig.model_validate(
        _schedule_payload(
            name="a-share-daily",
            job={
                "source_id": "a_share",
                "symbols": ["000001"],
                "frequencies": ["1d"],
                "date_range": {
                    "type": "fixed",
                    "start_date": "2026-05-01",
                    "end_date": "2026-05-18",
                },
            },
        )
    )

    payload = build_job_payload(
        schedule,
        _server_config(tmp_path),
        now=datetime.fromisoformat("2026-05-18T12:00:00+08:00"),
    )

    assert payload["source"] == "akshare"
    assert payload["exchange"] is None
    assert payload["symbols"] == ["000001.SZ"]
    assert payload["adjust"] == "qfq"
    assert payload["bars_root"] == str(tmp_path / "a_share" / "bars")


def test_invalid_schedule_fields_raise_validation_errors():
    with pytest.raises(ValueError, match="symbols"):
        DataScheduleConfig.model_validate(
            _schedule_payload(
                job={
                    "source_id": "bitget",
                    "symbols": [],
                    "frequencies": ["1h"],
                    "date_range": {"type": "last_n_days", "days": 7},
                }
            )
        )


def test_schedule_store_persists_schedule_snapshots(tmp_path: Path):
    store = DataSourceScheduleStore(
        tmp_path / "schedules.sqlite",
        now=lambda: datetime.fromisoformat("2026-05-18T09:00:00+08:00"),
    )

    snapshot = store.create(
        DataScheduleConfig.model_validate(_schedule_payload()),
        next_run_at=datetime.fromisoformat("2026-05-18T10:00:00+08:00"),
    )
    loaded = store.get(snapshot.schedule_id)

    assert loaded.schedule_id == snapshot.schedule_id
    assert loaded.name == "bitget-hourly"
    assert loaded.enabled is True
    assert loaded.status == "enabled"
    assert loaded.run_count == 0
    assert loaded.next_run_at is not None
    assert loaded.next_run_at.isoformat() == "2026-05-18T10:00:00+08:00"
    assert loaded.config.job.symbols == ["BTC/USDT"]
    assert [item.schedule_id for item in store.list()] == [snapshot.schedule_id]


def test_schedule_store_updates_deletes_and_records_runs(tmp_path: Path):
    store = DataSourceScheduleStore(
        tmp_path / "schedules.sqlite",
        now=lambda: datetime.fromisoformat("2026-05-18T09:00:00+08:00"),
    )
    snapshot = store.create(
        DataScheduleConfig.model_validate(_schedule_payload()),
        next_run_at=datetime.fromisoformat("2026-05-18T10:00:00+08:00"),
    )

    updated = store.update_state(
        snapshot.schedule_id,
        enabled=False,
        status="disabled",
        run_count=1,
        next_run_at=None,
        last_run_at=datetime.fromisoformat("2026-05-18T10:00:02+08:00"),
        last_job_id="job-1",
        last_error=None,
    )
    run = store.record_run(
        schedule_id=snapshot.schedule_id,
        due_at=datetime.fromisoformat("2026-05-18T10:00:00+08:00"),
        triggered_at=datetime.fromisoformat("2026-05-18T10:00:02+08:00"),
        status="submitted",
        job_id="job-1",
        error=None,
    )

    assert updated.enabled is False
    assert updated.status == "disabled"
    assert updated.run_count == 1
    assert run.status == "submitted"
    assert store.runs(snapshot.schedule_id)[0].job_id == "job-1"

    store.delete(snapshot.schedule_id)
    with pytest.raises(ValueError, match="Unknown schedule"):
        store.get(snapshot.schedule_id)


def test_schedule_service_create_update_enable_disable_and_run_now(tmp_path: Path):
    submitted = []
    current_now = datetime.fromisoformat("2026-05-18T09:00:00+08:00")

    def submit_job(payload):
        submitted.append(payload)
        return type(
            "Snapshot",
            (),
            {
                "job_id": f"job-{len(submitted)}",
                "status": "submitted",
                "to_dict": lambda self: {
                    "job_id": self.job_id,
                    "status": self.status,
                },
            },
        )()

    service = DataSourceScheduleService(
        store=DataSourceScheduleStore(
            tmp_path / "schedules.sqlite",
            now=lambda: current_now,
        ),
        server_config=_server_config(tmp_path),
        submit_job=submit_job,
        now=lambda: current_now,
    )

    created = service.create(
        _schedule_payload(
            enabled=False,
            repeat={"mode": "count", "count": 3},
        )
    )
    enabled = service.enable(created.schedule_id)
    updated = service.update(
        created.schedule_id,
        {"job": {"symbols": ["ETH/USDT"]}},
    )
    job = service.run_now(created.schedule_id)
    after_run_now = service.get(created.schedule_id)
    disabled = service.disable(created.schedule_id)

    assert created.enabled is False
    assert enabled.enabled is True
    assert enabled.next_run_at is not None
    assert updated.config.job.symbols == ["ETH/USDT"]
    assert job["job_id"] == "job-1"
    assert submitted[0]["source"] == "ccxt"
    assert after_run_now.enabled is True
    assert after_run_now.run_count == 1
    assert after_run_now.next_run_at is not None
    assert disabled.enabled is False
    assert service.runs(created.schedule_id)["runs"][0]["status"] == "submitted"


def test_scheduler_tick_submits_due_schedule_once(tmp_path: Path):
    submitted = []
    current_now = datetime.fromisoformat("2026-05-18T09:00:00+08:00")

    def submit_job(payload):
        submitted.append(payload)
        return type("Snapshot", (), {"job_id": "job-1", "status": "submitted"})()

    service = DataSourceScheduleService(
        store=DataSourceScheduleStore(
            tmp_path / "schedules.sqlite",
            now=lambda: current_now,
        ),
        server_config=_server_config(tmp_path),
        submit_job=submit_job,
        now=lambda: current_now,
    )
    snapshot = service.create(
        _schedule_payload(
            name="bitget-once",
            enabled=True,
            trigger={"type": "once", "run_at": "2026-05-18T09:00:00+08:00"},
            repeat={"mode": "forever"},
        )
    )
    scheduler = DataSourceScheduler(service=service, poll_seconds=0.01)

    scheduler.tick()

    assert len(submitted) == 1
    updated = service.get(snapshot.schedule_id)
    assert updated.run_count == 1
    assert updated.status == "completed"
    assert updated.enabled is False
    assert updated.next_run_at is None


def test_scheduler_tick_skips_when_previous_job_is_still_running(tmp_path: Path):
    submitted = []
    current_now = datetime.fromisoformat("2026-05-18T09:00:00+08:00")

    def submit_job(payload):
        submitted.append(payload)
        return type("Snapshot", (), {"job_id": "job-new", "status": "submitted"})()

    def get_job(job_id):
        return {"job_id": job_id, "status": "running"}

    store = DataSourceScheduleStore(
        tmp_path / "schedules.sqlite",
        now=lambda: current_now,
    )
    service = DataSourceScheduleService(
        store=store,
        server_config=_server_config(tmp_path),
        submit_job=submit_job,
        get_job=get_job,
        now=lambda: current_now,
    )
    snapshot = service.create(_schedule_payload(enabled=True, overlap_policy="skip"))
    store.update_state(
        snapshot.schedule_id,
        enabled=True,
        status="enabled",
        run_count=0,
        next_run_at=current_now,
        last_run_at=None,
        last_job_id="job-running",
        last_error=None,
    )
    scheduler = DataSourceScheduler(service=service, poll_seconds=0.01)

    scheduler.tick()

    assert submitted == []
    updated = service.get(snapshot.schedule_id)
    assert updated.run_count == 0
    assert updated.next_run_at is not None
    assert updated.next_run_at.isoformat() == "2026-05-18T10:00:00+08:00"
    assert service.runs(snapshot.schedule_id)["runs"][0]["status"] == "skipped"
