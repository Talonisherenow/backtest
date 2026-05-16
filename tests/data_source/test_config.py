from pathlib import Path

import pytest

from backtest.data_source.config import (
    DataSourceServerConfig,
    DataSourceSpec,
    build_default_source_specs,
)


def _spec(tmp_path: Path, source_id: str = "a_share") -> DataSourceSpec:
    bars_root = tmp_path / source_id / "bars"
    bars_root.mkdir(parents=True, exist_ok=True)
    return DataSourceSpec(
        source_id=source_id,
        source_label="A-share",
        asset_class="equity",
        bars_root=bars_root,
        metadata_path=tmp_path / source_id / "metadata.sqlite",
        adjust="qfq",
        catalog_source="akshare",
    )


def test_source_spec_public_dict_exposes_browser_safe_fields(tmp_path: Path):
    spec = _spec(tmp_path)

    assert spec.public_dict() == {
        "source_id": "a_share",
        "source_label": "A-share",
        "asset_class": "equity",
        "bars": True,
        "crawl_jobs": True,
    }


def test_server_config_rejects_duplicate_source_ids(tmp_path: Path):
    with pytest.raises(ValueError, match="Duplicate source id"):
        DataSourceServerConfig(sources=[_spec(tmp_path, "dup"), _spec(tmp_path, "dup")])


def test_server_config_rejects_missing_bars_root(tmp_path: Path):
    spec = DataSourceSpec(
        source_id="missing",
        source_label="Missing",
        asset_class="equity",
        bars_root=tmp_path / "missing-bars",
        metadata_path=tmp_path / "metadata.sqlite",
        adjust="qfq",
        catalog_source="akshare",
    )

    with pytest.raises(ValueError, match="bars_root does not exist"):
        DataSourceServerConfig(sources=[spec])


def test_server_config_finds_source_by_id(tmp_path: Path):
    spec = _spec(tmp_path, "bitget")
    config = DataSourceServerConfig(sources=[spec])

    assert config.source("bitget") is spec
    with pytest.raises(ValueError, match="Unknown source"):
        config.source("a_share")


def test_server_config_normalizes_api_token(tmp_path: Path):
    config = DataSourceServerConfig(sources=[_spec(tmp_path)], api_token="  secret  ")

    assert config.api_token == "secret"

    with pytest.raises(ValueError, match="api_token must not be blank"):
        DataSourceServerConfig(sources=[_spec(tmp_path, "other")], api_token="  ")


def test_build_default_source_specs_uses_expected_source_metadata(tmp_path: Path):
    bitget_root = tmp_path / "bitget" / "bars"
    a_share_root = tmp_path / "a_share" / "bars"
    universe = tmp_path / "universe.json"
    bitget_root.mkdir(parents=True)
    a_share_root.mkdir(parents=True)
    universe.write_text("{}", encoding="utf-8")

    specs = build_default_source_specs(
        bitget_bars_root=bitget_root,
        bitget_metadata_path=tmp_path / "bitget.sqlite",
        a_share_bars_root=a_share_root,
        a_share_metadata_path=tmp_path / "a_share.sqlite",
        include_bitget=True,
        include_a_share=True,
        a_share_universe=universe,
    )

    assert [(spec.source_id, spec.source_label, spec.asset_class) for spec in specs] == [
        ("bitget", "Bitget", "crypto"),
        ("a_share", "A-share", "equity"),
    ]
    assert specs[0].adjust == "none"
    assert specs[0].catalog_source == "ccxt:bitget"
    assert specs[1].adjust == "qfq"
    assert specs[1].catalog_source == "akshare"
    assert specs[1].universe_path == universe


def test_build_default_source_specs_includes_both_sources_by_default(tmp_path: Path):
    bitget_root = tmp_path / "bitget" / "bars"
    a_share_root = tmp_path / "a_share" / "bars"
    bitget_root.mkdir(parents=True)
    a_share_root.mkdir(parents=True)

    specs = build_default_source_specs(
        bitget_bars_root=bitget_root,
        bitget_metadata_path=tmp_path / "bitget.sqlite",
        a_share_bars_root=a_share_root,
        a_share_metadata_path=tmp_path / "a_share.sqlite",
    )

    assert [spec.source_id for spec in specs] == ["bitget", "a_share"]


def test_build_default_source_specs_omits_missing_universe_and_requires_one_source(tmp_path: Path):
    bitget_root = tmp_path / "bitget" / "bars"
    bitget_root.mkdir(parents=True)

    specs = build_default_source_specs(
        bitget_bars_root=bitget_root,
        bitget_metadata_path=tmp_path / "bitget.sqlite",
        a_share_bars_root=tmp_path / "a_share" / "bars",
        a_share_metadata_path=tmp_path / "a_share.sqlite",
        include_bitget=True,
        include_a_share=False,
        a_share_universe=tmp_path / "missing.json",
    )

    assert len(specs) == 1
    assert specs[0].universe_path is None

    with pytest.raises(ValueError, match="At least one data source"):
        build_default_source_specs(
            bitget_bars_root=bitget_root,
            bitget_metadata_path=tmp_path / "bitget.sqlite",
            a_share_bars_root=tmp_path / "a_share" / "bars",
            a_share_metadata_path=tmp_path / "a_share.sqlite",
            include_bitget=False,
            include_a_share=False,
        )
