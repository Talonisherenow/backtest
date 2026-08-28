# Instrument Workbench Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a workbench home overview and `/instruments` page for managing instruments and tag/list groupings.

**Architecture:** Extend the existing `backtest.charts.workbench_server` HTML-rendering pattern with a new instrument manager shell. Reuse the existing data API URL/token helpers in browser JavaScript and route `/instruments` from the workbench HTTP server.

**Tech Stack:** Python stdlib HTTP server, generated HTML/CSS/JavaScript string templates, pytest, Browser plugin for local visual verification.

---

## File Structure

- Modify `backtest/charts/workbench_server.py`: add `/instruments` route, render function, home entry, summary JavaScript, and page shell JavaScript.
- Modify `tests/charts/test_workbench_server.py`: add assertions for home entry, instrument page shell, and route serving.

## Task 1: Home Entry And Summary

**Files:**
- Modify: `tests/charts/test_workbench_server.py`
- Modify: `backtest/charts/workbench_server.py`

- [ ] **Step 1: Write the failing test**

```python
def test_render_workbench_index_html_links_instrument_manager():
    html = render_workbench_index_html(data_api_base_url="http://127.0.0.1:8768/")

    assert 'href="/instruments"' in html
    assert "Instrument Lists" in html
    assert 'id="instrumentOverviewSummary"' in html
    assert 'fetch(dataApiUrl("/api/instruments?limit=1"), dataApiRequestOptions())' in html
    assert 'fetch(dataApiUrl("/api/instrument-tags"), dataApiRequestOptions())' in html
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/charts/test_workbench_server.py::test_render_workbench_index_html_links_instrument_manager -q`

Expected: FAIL because the home page has no instrument entry.

- [ ] **Step 3: Implement the home entry**

Add an `Instrument Lists` home link, an `instrumentOverviewSummary` element, and
JavaScript that loads instrument count and tag summaries when a data API is
configured.

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/charts/test_workbench_server.py::test_render_workbench_index_html_links_instrument_manager -q`

Expected: PASS.

## Task 2: Instrument Page Shell

**Files:**
- Modify: `tests/charts/test_workbench_server.py`
- Modify: `backtest/charts/workbench_server.py`

- [ ] **Step 1: Write the failing page-shell test**

```python
def test_render_instrument_manager_html_uses_instrument_api():
    html = workbench_server.render_instrument_manager_html(
        data_api_base_url="http://127.0.0.1:8768/",
        data_api_token="viewer-token",
    )

    assert "Instrument Lists" in html
    assert "instrument-manager-payload" in html
    assert '"data_api_base_url":"http://127.0.0.1:8768"' in html
    assert 'id="instrumentRows"' in html
    assert 'id="instrumentTagList"' in html
    assert 'fetch(instrumentApiUrl(), instrumentRequestOptions())' in html
    assert 'fetch(dataApiUrl("/api/instrument-tags"), instrumentRequestOptions())' in html
    assert 'fetch(dataApiUrl("/api/instruments"), instrumentMutationOptions("POST", payload))' in html
    assert 'fetch(dataApiUrl(`/api/instrument-tags/${encodeURIComponent(tagId)}/members`), instrumentMutationOptions("POST", payload))' in html
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/charts/test_workbench_server.py::test_render_instrument_manager_html_uses_instrument_api -q`

Expected: FAIL because `render_instrument_manager_html` does not exist.

- [ ] **Step 3: Implement the page shell**

Create `render_instrument_manager_html()` with the three-zone layout: summary
band, left tag/list panel, main table, right details/editor panel.

- [ ] **Step 4: Run the page-shell test**

Run: `uv run pytest tests/charts/test_workbench_server.py::test_render_instrument_manager_html_uses_instrument_api -q`

Expected: PASS.

## Task 3: Workbench Route

**Files:**
- Modify: `tests/charts/test_workbench_server.py`
- Modify: `backtest/charts/workbench_server.py`

- [ ] **Step 1: Write the failing route test**

```python
def test_workbench_server_serves_instrument_manager_route(monkeypatch):
    captured = {}

    class FakeKlineService:
        def __init__(self, **kwargs):
            pass

    class FakeStrategyService:
        def __init__(self, **kwargs):
            pass

    class FakeServer:
        def __init__(self, address, handler_class):
            captured["handler_class"] = handler_class

        def serve_forever(self):
            return None

        def server_close(self):
            return None

    monkeypatch.setattr(workbench_server, "KlineCacheService", FakeKlineService)
    monkeypatch.setattr(workbench_server, "StrategyResultsService", FakeStrategyService)
    monkeypatch.setattr(workbench_server, "ThreadingHTTPServer", FakeServer)

    workbench_server.serve_chart_workbench(
        kline_sources=[],
        results_roots=[],
        bars_root=".",
        data_api_base_url="http://data-host:8768/",
        data_api_token="viewer-token",
    )
    handler = object.__new__(captured["handler_class"])
    handler.path = "/instruments"
    sent = {}
    handler._send_bytes = lambda body, content_type, status=None: sent.update(
        body=body,
        content_type=content_type,
    )

    handler.do_GET()

    assert sent["content_type"] == "text/html; charset=utf-8"
    assert b"Instrument Lists" in sent["body"]
    assert b"http://data-host:8768" in sent["body"]
```

- [ ] **Step 2: Run the route test to verify it fails**

Run: `uv run pytest tests/charts/test_workbench_server.py::test_workbench_server_serves_instrument_manager_route -q`

Expected: FAIL because `/instruments` returns not found.

- [ ] **Step 3: Wire `/instruments`**

Build `instrument_html` in `serve_chart_workbench()` and return it when
`parsed.path == "/instruments"`.

- [ ] **Step 4: Run route test**

Run: `uv run pytest tests/charts/test_workbench_server.py::test_workbench_server_serves_instrument_manager_route -q`

Expected: PASS.

## Task 4: Verification

**Files:**
- No additional files unless verification exposes a defect.

- [ ] **Step 1: Run focused tests**

Run:

```bash
uv run pytest tests/charts/test_workbench_server.py tests/data_source/test_api.py tests/data_source/test_server.py -q
```

Expected: PASS.

- [ ] **Step 2: Start workbench and verify in browser**

Run the workbench server against available local roots, open `/` and
`/instruments` in the in-app browser, and verify both pages are nonblank and
show the new entry/page.

- [ ] **Step 3: Run full suite**

Run:

```bash
uv run pytest -q
```

Expected: PASS.

