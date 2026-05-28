from backtest.charts import workbench_server
from backtest.charts.workbench_server import build_kline_shell_payload, render_workbench_index_html


def test_render_workbench_index_html_links_both_chart_apps():
    html = render_workbench_index_html()

    assert "Backtest Workbench" in html
    assert 'href="/strategy-results"' in html
    assert "Strategy Results" in html
    assert 'href="/kline"' in html
    assert "K-line Viewer" in html


def test_render_workbench_index_html_links_instrument_manager_once():
    html = render_workbench_index_html(data_api_base_url="http://127.0.0.1:8768/")

    assert 'href="/instruments"' in html
    assert "Instrument Lists" in html
    assert 'id="instrumentOverviewSummary"' not in html
    assert 'fetch(dataApiUrl("/api/instruments?limit=1"), dataApiRequestOptions())' not in html
    assert 'fetch(dataApiUrl("/api/instrument-tags"), dataApiRequestOptions())' not in html


def test_render_instrument_manager_html_uses_instrument_api():
    html = workbench_server.render_instrument_manager_html(
        data_api_base_url="http://127.0.0.1:8768/",
        data_api_token="viewer-token",
    )

    assert "Instrument Lists" in html
    assert "instrument-manager-payload" in html
    assert '"data_api_base_url":"http://127.0.0.1:8768"' in html
    assert '"data_api_token":"viewer-token"' in html
    assert 'id="instrumentSummaryBand"' not in html
    assert "function renderSummary()" not in html
    assert '<div class="header-actions">' in html
    assert '<a class="home-link" href="/">Workbench Home</a>' in html
    assert '<a href="/">Workbench Home</a>' not in html
    assert 'id="instrumentRows"' in html
    assert 'id="instrumentPaginationMeta"' in html
    assert 'id="instrumentPreviousPageButton"' in html
    assert 'id="instrumentNextPageButton"' in html
    assert 'id="instrumentPageSizeSelect"' in html
    assert 'id="instrumentTagList"' in html
    assert 'id="openTagDialogButton"' in html
    assert '<dialog id="tagCreateDialog"' in html
    assert '<div class="color-preset-field" aria-label="List color">' in html
    assert '<span>Color</span>' in html
    assert 'id="tagColorInput" type="hidden" value="#1d5fd1"' in html
    assert 'id="tagColorSwatches" class="color-swatch-list" role="radiogroup" aria-label="List color"' in html
    assert 'class="color-swatch active" data-tag-color="#1d5fd1"' in html
    assert 'data-tag-color="#168a5a"' in html
    assert 'type="color"' not in html
    assert 'placeholder="#1d5fd1"' not in html
    assert ".color-preset-field" in html
    assert "function selectTagColor(color)" in html
    assert "function resetTagColorSelection()" in html
    assert 'data-special-tag="all"' in html
    assert "function isDefaultSourceTag(tag)" in html
    assert 'const deleteButton = isDefaultSourceTag(tag) ? "" :' in html
    assert "${deleteButton}" in html
    assert 'data-delete-tag-id="${escapeHtml(tag.tag_id)}"' in html
    assert 'class="tag-delete-button"' in html
    assert 'aria-label="Delete ${escapeHtml(tag.name)}"' in html
    assert 'title="Delete list"' in html
    assert 'type="button">×</button>' in html
    assert 'type="button">Delete</button>' not in html
    assert 'class="tag-delete-button danger"' not in html
    assert 'id="clearTagButton"' not in html
    assert "function openTagDialog()" in html
    assert "function deleteInstrumentTag(tagId)" in html
    assert "if (isDefaultSourceTag(tag || { tag_id: tagId })) return;" in html
    assert 'window.confirm(`Delete list "${tagLabel}"? This will remove the list from all instruments.`)' in html
    assert 'dataApiUrl(`/api/instrument-tags/${encodeURIComponent(tagId)}`)' in html
    assert "if (instrumentState.selectedTagId === tagId)" in html
    assert "instrumentApiUrl({ includeTag: false, limit: 1, offset: 0 })" in html
    assert 'id="instrumentSearchButton"' in html
    assert ">Search</button>" in html
    assert 'id="openInstrumentDialogButton"' in html
    assert ">New</button>" in html
    assert '<dialog id="instrumentCreateDialog"' in html
    assert 'id="openInstrumentSyncDialogButton"' in html
    assert ">Sources</button>" in html
    assert '<dialog id="instrumentSyncDialog"' in html
    assert 'class="modal-dialog wide-modal"' in html
    assert 'id="instrumentSourceRows"' in html
    assert 'id="instrumentSyncScheduleRows"' in html
    assert 'id="instrumentSyncScheduleForm"' in html
    assert 'id="instrumentRefreshButton"' not in html
    assert 'id="openKlineButton"' in html
    assert "Open K-line" in html
    assert 'id="deleteInstrumentButton"' not in html
    assert "Delete ${instrument.instrument_id}" not in html
    assert "function klineUrlForInstrument(instrument)" in html
    assert 'params.set("symbol", instrument.symbol || instrument.instrument_id);' in html
    assert "function instrumentDisplaySymbol(instrument)" in html
    assert "function marketLabel(value)" in html
    assert "function settleCurrency(instrument)" in html
    assert "<th>Settle</th>" in html
    assert "<th>Synced</th>" in html
    assert "function formatInstrumentSyncTime(value)" in html
    assert '<td><div class="instrument-symbol-cell">' in html
    assert '<strong>${escapeHtml(instrumentDisplaySymbol(instrument))}</strong>' in html
    assert "<td>${escapeHtml(settleCurrency(instrument))}</td>" in html
    assert "<td>${escapeHtml(formatInstrumentSyncTime(instrument.updated_at))}</td>" in html
    assert '<div class="detail-row"><span>ID</span><strong>${escapeHtml(instrument.instrument_id || "")}</strong></div>' in html
    assert '<div class="detail-row"><span>Synced</span><strong>${escapeHtml(formatInstrumentSyncTime(instrument.updated_at))}</strong></div>' in html
    assert '<td><strong>${escapeHtml(instrument.instrument_id)}</strong></td>' not in html
    assert "function isDefaultInstrumentTag(tag, instrument)" in html
    assert "function renderDetailTagChip(tag, instrument)" in html
    assert "if (isDefaultInstrumentTag(tag, instrument))" in html
    assert 'tags.map((tag) => renderDetailTagChip(tag, instrument)).join("")' in html
    assert "if (isDefaultInstrumentTag({ tag_id: tagId }, instrument)) return;" in html
    assert "<h3>Add Instrument</h3>" not in html
    assert "function openInstrumentDialog()" in html
    assert 'fetch(instrumentApiUrl(), instrumentRequestOptions())' in html
    assert "page: 1" in html
    assert "pageSize: 25" in html
    assert 'params.set("limit", String(instrumentState.pageSize));' in html
    assert 'params.set("offset", String((instrumentState.page - 1) * instrumentState.pageSize));' in html
    assert "function instrumentPageCount()" in html
    assert "function resetInstrumentPaging()" in html
    assert "function renderInstrumentPagination()" in html
    assert 'document.getElementById("instrumentPreviousPageButton").addEventListener("click"' in html
    assert 'document.getElementById("instrumentNextPageButton").addEventListener("click"' in html
    assert 'document.getElementById("instrumentPageSizeSelect").addEventListener("change"' in html
    assert "overflow-wrap: anywhere;" in html
    assert 'fetch(dataApiUrl("/api/instrument-tags"), instrumentRequestOptions())' in html
    assert 'fetch(dataApiUrl("/api/instruments"), instrumentMutationOptions("POST", payload))' in html
    assert 'fetch(dataApiUrl("/api/instrument-sources"), instrumentRequestOptions())' in html
    assert 'fetch(dataApiUrl("/api/instrument-sync/run"), instrumentMutationOptions("POST", payload))' in html
    assert 'fetch(dataApiUrl("/api/instrument-sync/schedules"), instrumentRequestOptions())' in html
    assert 'data-sync-source-id="${escapeHtml(source.source_id)}"' in html
    assert 'data-sync-schedule-action="run"' in html
    assert "function loadInstrumentSyncState()" in html
    assert "function runInstrumentSourceSync(sourceId)" in html
    assert "function createInstrumentSyncSchedule(event)" in html
    assert 'source_id: sourceId || undefined' in html
    assert 'fetch(dataApiUrl(`/api/instrument-tags/${encodeURIComponent(tagId)}/members`), instrumentMutationOptions("POST", payload))' in html


def test_render_workbench_index_html_hosts_data_source_monitor():
    html = render_workbench_index_html(
        data_api_base_url="http://127.0.0.1:8768/",
        data_api_token="monitor-token",
    )

    assert "workbench-index-payload" in html
    assert '"data_api_base_url":"http://127.0.0.1:8768"' in html
    assert '"data_api_token":"monitor-token"' in html
    assert 'id="dataSourceMonitor"' in html
    assert 'id="dataSourceDrawer"' in html
    assert "left: 50%;" in html
    assert "transform: translateX(-50%);" in html
    assert "width: min(1180px, calc(100vw - 32px));" in html
    assert "height: min(76vh, 760px);" in html
    assert 'role="tablist" aria-label="Data source monitor sections"' in html
    assert 'data-drawer-tab="schedules"' in html
    assert 'data-drawer-tab="tasks"' in html
    assert 'id="scheduleDrawerPanel"' in html
    assert 'id="taskDrawerPanel"' in html
    assert 'aria-controls="scheduleDrawerPanel"' in html
    assert 'aria-controls="taskDrawerPanel"' in html
    assert 'id="dataSourceTabs"' in html
    assert 'id="taskSymbolSearch"' in html
    assert 'id="taskFrequencyFilters"' in html
    assert 'id="taskStatusFilters"' in html
    assert 'id="taskPreviousPageButton"' in html
    assert 'id="taskNextPageButton"' in html
    assert 'id="taskPageSizeSelect"' in html
    assert 'id="schedulePreviousPageButton"' in html
    assert 'id="scheduleNextPageButton"' in html
    assert 'id="schedulePageSizeSelect"' in html
    assert 'id="schedulePaginationMeta"' in html
    assert 'id="scheduleCreateButton"' in html
    assert 'id="scheduleRunPreviousPageButton"' in html
    assert 'id="scheduleRunNextPageButton"' in html
    assert 'id="scheduleRunPageSizeSelect"' in html
    assert 'id="scheduleRunPaginationMeta"' in html
    assert 'id="dataScheduleSummary"' in html
    assert 'id="dataScheduleRows"' in html
    assert 'id="dataScheduleRunRows"' in html
    assert "Schedule controls and crawl task monitor" in html
    assert "Schedule" in html
    assert "Recent Runs" in html
    assert "Trigger" in html
    assert "Repeat" in html
    assert "Next Run" in html
    assert "Last Job" in html
    assert "Range" in html
    assert "Triggered" in html
    assert "function dataApiUrl(path)" in html
    assert "function dataApiRequestOptions()" in html
    assert "function setDrawerTab(tabId)" in html
    assert "function paginatedItems(items, page, pageSize)" in html
    assert "function renderSchedulePagination(pageInfo)" in html
    assert "function renderScheduleRunPagination(pageInfo)" in html
    assert '"Authorization", `Bearer ${payload.data_api_token}`' in html
    assert 'fetch(dataApiUrl("/api/data-sources"), dataApiRequestOptions())' in html
    assert 'fetch(dataApiUrl(`/api/data/tasks/summary?source_id=${encodeURIComponent(source.source_id)}`), dataApiRequestOptions())' in html
    assert 'fetch(taskPageUrl(source.source_id, filters), dataApiRequestOptions())' in html
    assert 'fetch(dataApiUrl("/api/data/jobs"), dataApiRequestOptions())' in html
    assert 'fetch(dataApiUrl("/api/data/schedules"), dataApiRequestOptions())' in html
    assert 'fetch(dataApiUrl(`/api/data/schedules/${encodeURIComponent(schedule.schedule_id)}/runs`), dataApiRequestOptions())' in html
    assert "function renderScheduleRows()" in html
    assert "function renderScheduleRunRows()" in html
    assert "function formatTaskRange(task)" in html
    assert "function formatScheduleDateRange(schedule, anchorValue)" in html
    assert 'const WORKBENCH_DISPLAY_TIME_ZONE = "Asia/Shanghai";' in html
    assert "timeZone: WORKBENCH_DISPLAY_TIME_ZONE" in html
    assert "function datePartsInDisplayZone(value)" in html
    assert "task.start_date" in html
    assert "task.end_date" in html
    assert "DATA_MONITOR_REFRESH_MS = 10000" in html
    assert 'document.addEventListener("visibilitychange", refreshDataMonitorWhenVisible)' in html
    assert "Submit" not in html
    assert "Retry" not in html
    assert "Cancel" not in html


def test_render_workbench_index_html_supports_schedule_controls():
    html = render_workbench_index_html(
        data_api_base_url="http://127.0.0.1:8768/",
        data_api_token="monitor-token",
    )

    assert "Actions" in html
    assert 'data-schedule-action="toggle"' in html
    assert "schedule-toggle-button" in html
    assert "danger-button" in html
    assert "success-button" in html
    assert 'data-schedule-action="run"' in html
    assert 'data-schedule-action="edit"' in html
    assert 'id="scheduleEditDialog"' in html
    assert 'id="scheduleEditForm"' in html
    assert 'id="scheduleEditName"' in html
    assert 'id="scheduleEditTriggerType"' in html
    assert 'class="schedule-editor-summary" id="scheduleEditSummary"' in html
    assert 'data-schedule-trigger="interval"' in html
    assert 'data-schedule-trigger="daily"' in html
    assert 'data-schedule-trigger="weekly"' in html
    assert 'data-schedule-trigger="once"' in html
    assert 'value="seconds"' in html
    assert 'id="scheduleEditTime" type="hidden"' in html
    assert "box-sizing: border-box;" in html
    assert 'class="schedule-editor-grid trigger-grid"' in html
    assert ".schedule-editor-grid.trigger-grid" in html
    assert ".schedule-editor-field.number-field" in html
    assert ".schedule-editor-field.unit-field" in html
    assert ".schedule-editor-field.delay-field" in html
    assert ".schedule-editor-field.datetime-field" in html
    assert 'class="schedule-editor-field number-field" data-trigger-field="interval"' in html
    assert 'class="schedule-editor-field unit-field" data-trigger-field="interval"' in html
    assert 'id="scheduleEditStartAt" type="datetime-local" step="1"' in html
    assert 'class="schedule-editor-field datetime-field" data-trigger-field="interval daily weekly"' in html
    assert 'class="schedule-editor-field delay-field"' in html
    assert 'class="schedule-editor-field unit-field delay-unit-field"' in html
    assert 'id="scheduleEditStartAtPicker"' not in html
    assert 'id="scheduleEditStartDateButton"' not in html
    assert 'id="scheduleEditStartTimeButton"' not in html
    assert 'id="scheduleEditStartDatePart"' not in html
    assert 'id="scheduleEditStartTimePart"' not in html
    assert 'id="scheduleEditRunAt" type="datetime-local" step="1"' in html
    assert 'id="scheduleEditUntil" type="datetime-local" step="1"' in html
    assert 'id="scheduleEditDaysOfWeekPills"' in html
    assert 'id="scheduleEditRepeatMode"' in html
    assert '<select id="scheduleEditSourceId">' in html
    assert '<input id="scheduleEditSourceId" type="text"' not in html
    assert 'id="scheduleEditSymbols" type="hidden"' in html
    assert 'id="scheduleEditTargetMode" type="hidden"' in html
    assert 'data-schedule-target-mode="symbols"' in html
    assert 'data-schedule-target-mode="tag"' in html
    assert 'id="scheduleInstrumentSearch"' in html
    assert 'id="scheduleInstrumentSearchResults"' in html
    assert 'id="scheduleSelectedInstruments"' in html
    assert 'id="scheduleEditTagId"' in html
    assert 'id="scheduleTagMemberPreview"' in html
    assert 'id="scheduleEditFrequencies" type="hidden"' in html
    assert 'class="frequency-multiselect" id="scheduleEditFrequencyDropdown"' in html
    assert 'id="scheduleEditFrequencyToggle"' in html
    assert 'id="scheduleEditFrequencySummary"' in html
    assert 'id="scheduleEditFrequencyMenu"' in html
    assert 'id="scheduleEditFrequencyPills"' in html
    assert "Select frequencies" in html
    for frequency in ["1d", "4h", "1h", "15m", "1m"]:
        assert f'value="{frequency}"' in html
    assert 'id="scheduleEditDateRangeType"' in html
    assert 'id="scheduleEditRangePreset"' in html
    assert 'id="scheduleEditRangeValue"' in html
    assert 'value="last_n_minutes"' in html
    assert 'value="last_n_hours"' in html
    assert 'value="last_n_days"' in html
    assert "Last N mins" in html
    assert "Last N hours" in html
    assert "Last N days" in html
    assert 'id="scheduleEditExecutionDelayValue"' in html
    assert 'id="scheduleEditExecutionDelayUnit"' in html
    assert 'value="minutes"' in html
    assert "Execution delay" in html
    assert "End lag" not in html
    assert "End Offset" not in html
    assert "Request gap seconds" in html
    assert "Page Delay Seconds" not in html
    assert 'id="scheduleEditRefreshExisting"' in html
    assert "function toggleSchedule(scheduleId)" in html
    assert "function confirmScheduleToggle(schedule)" in html
    assert "window.confirm(message)" in html
    assert "function openNewScheduleEditor()" in html
    assert "function defaultNewScheduleConfig()" in html
    assert "function openScheduleEditor(scheduleId)" in html
    assert "function scheduleEditorMode()" in html
    assert "function syncScheduleEditorControls()" in html
    assert "function setScheduleTriggerMode(triggerType)" in html
    assert "function selectedWeekdays()" in html
    assert "function selectedFrequencies()" in html
    assert "function updateFrequencySummary()" in html
    assert "function toggleFrequencyMenu()" in html
    assert "function closeFrequencyMenu()" in html
    assert "function renderScheduleSourceOptions(selectedId)" in html
    assert "function loadScheduleTargetTags(sourceId)" in html
    assert "function searchScheduleInstruments()" in html
    assert "const SCHEDULE_SELECTED_INSTRUMENT_DISPLAY_LIMIT = 20;" in html
    assert "const SCHEDULE_UNSELECTED_INSTRUMENT_DISPLAY_TARGET = 20;" in html
    assert "const SCHEDULE_INSTRUMENT_SEARCH_PAGE_SIZE = 100;" in html
    assert "function visibleScheduleSelectedInstruments()" in html
    assert "function scheduleInstrumentIdentityKeys(instrument)" in html
    assert "function scheduleInstrumentIdentityKeySet(instruments)" in html
    assert "function scheduleInstrumentAlreadySelected(instrument, selectedKeys)" in html
    assert '`symbol:${symbolKey}`' in html
    assert "function enrichSelectedScheduleInstruments(instruments)" in html
    assert "name: current.name || detail.name || \"\"," in html
    assert "function scheduleSelectedInstrumentsForDisplay()" in html
    assert "state.selectedInstruments.filter((instrument) => scheduleInstrumentMatchesQuery(instrument, state.searchQuery))" in html
    assert "function scheduleSearchResultsForDisplay()" in html
    assert "function visibleScheduleSearchResults()" in html
    assert ".slice(0, SCHEDULE_UNSELECTED_INSTRUMENT_DISPLAY_TARGET)" in html
    assert "return state.searchResults.filter((instrument) => !scheduleInstrumentAlreadySelected(instrument, selectedKeys));" in html
    assert "const visibleInstruments = visibleScheduleSelectedInstruments();" in html
    assert "displayInstruments.length > visibleInstruments.length" in html
    assert "&hellip; +${hiddenCount} more" in html
    assert "No additional instruments match this search." in html
    assert "while (!state.searchQuery && scheduleSearchResultsForDisplay().length < SCHEDULE_UNSELECTED_INSTRUMENT_DISPLAY_TARGET)" in html
    assert "enrichSelectedScheduleInstruments(state.searchResults);" in html
    assert "function loadScheduleTagMembers()" in html
    assert "async function fetchScheduleTagMembersFromInstruments(sourceId, tagId)" in html
    assert "const pageSize = 500;" in html
    assert "const effectivePageSize = Number.isFinite(responseLimit) && responseLimit > 0 ? responseLimit : pageSize;" in html
    assert "page.length < effectivePageSize" in html
    assert "fetchScheduleTagMembersFromInstruments(sourceId, tagId)" in html
    assert 'params.set("tag", tagId);' in html
    assert "function buildScheduleTargetPayload()" in html
    assert "function syncScheduleTargetControls()" in html
    assert "target: {" in html
    assert 'fetch(dataApiUrl(`/api/instruments?${params.toString()}`), dataApiRequestOptions())' in html
    assert 'fetch(dataApiUrl(`/api/instrument-tags?${params.toString()}`), dataApiRequestOptions())' in html
    assert '`/api/instrument-tags/${encodeURIComponent(tagId)}/members?${params.toString()}`' in html
    assert "function openNativePicker(inputId)" not in html
    assert "function syncStartAtPickerLabels()" not in html
    assert "function combineDateTimeLocal(dateValue, timeValue)" not in html
    assert "function toDatetimeLocalValue(value)" in html
    assert "function saveScheduleEdits(event)" in html
    assert 'fetch(dataApiUrl("/api/data/schedules"), dataApiMutationOptions("POST", payload))' in html
    assert "responsePayload = await response.json();" in html
    assert "responsePayload?.config?.trigger?.execution_delay_seconds" in html
    assert "does not support execution delay yet" in html
    assert 'fetch(dataApiUrl(`/api/data/schedules/${encodeURIComponent(schedule.schedule_id)}/${schedule.enabled ? "disable" : "enable"}`), dataApiMutationOptions("POST"))' in html
    assert 'fetch(dataApiUrl(`/api/data/schedules/${encodeURIComponent(schedule.schedule_id)}/run-now`), dataApiMutationOptions("POST"))' in html
    assert 'fetch(dataApiUrl(`/api/data/schedules/${encodeURIComponent(schedule.schedule_id)}`), dataApiMutationOptions("PATCH", payload))' in html


def test_build_kline_shell_payload_includes_remote_data_api_base_url():
    payload = build_kline_shell_payload(
        default_window_size=5000,
        data_api_base_url="http://data-host:8768/",
        data_api_token="viewer-token",
    )

    assert payload == {
        "mode": "dynamic",
        "default_window_size": 5000,
        "links": {"workbench_home": "/"},
        "data_api_base_url": "http://data-host:8768",
        "data_api_token": "viewer-token",
    }


def test_build_kline_shell_payload_includes_default_selection():
    payload = build_kline_shell_payload(
        default_window_size=5000,
        data_api_base_url="http://data-host:8768/",
        data_api_token="viewer-token",
        default_source_id="a_share",
        default_symbol="000001.SZ",
        default_frequency="1d",
    )

    assert payload["default_source_id"] == "a_share"
    assert payload["default_symbol"] == "000001.SZ"
    assert payload["default_frequency"] == "1d"


def test_workbench_home_receives_remote_data_api_base_url(monkeypatch):
    captured = {}

    class FakeKlineService:
        def __init__(self, **kwargs):
            pass

    class FakeStrategyService:
        def __init__(self, **kwargs):
            pass

    class FakeServer:
        def __init__(self, address, handler_class):
            pass

        def serve_forever(self):
            return None

        def server_close(self):
            return None

    def fake_render_strategy_results_catalog_html(payload):
        captured["strategy_payload"] = payload
        return "strategy shell"

    def fake_render_workbench_index_html(*, data_api_base_url=None, data_api_token=None):
        captured["home_data_api_base_url"] = data_api_base_url
        captured["home_data_api_token"] = data_api_token
        return "home shell"

    monkeypatch.setattr(workbench_server, "KlineCacheService", FakeKlineService)
    monkeypatch.setattr(workbench_server, "StrategyResultsService", FakeStrategyService)
    monkeypatch.setattr(workbench_server, "ThreadingHTTPServer", FakeServer)
    monkeypatch.setattr(workbench_server, "render_workbench_index_html", fake_render_workbench_index_html)
    monkeypatch.setattr(
        workbench_server,
        "render_strategy_results_catalog_html",
        fake_render_strategy_results_catalog_html,
    )

    workbench_server.serve_chart_workbench(
        kline_sources=[],
        results_roots=[],
        bars_root=".",
        data_api_base_url="http://data-host:8768/",
        data_api_token="viewer-token",
    )

    assert captured["home_data_api_base_url"] == "http://data-host:8768"
    assert captured["home_data_api_token"] == "viewer-token"
    assert captured["strategy_payload"] == {
        "mode": "dynamic",
        "title": "Strategy Results",
        "links": {"workbench_home": "/"},
    }


def test_workbench_server_supports_legacy_and_kline_api_manifest_routes(monkeypatch):
    captured = {}

    class FakeKlineService:
        def __init__(self, **kwargs):
            pass

        def manifest(self, *, default_window_size):
            return {"window": default_window_size}

        def bars(self, **kwargs):
            return {"source_id": kwargs["source_id"], "symbol": kwargs["symbol"]}

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
        default_window_size=321,
    )
    handler_class = captured["handler_class"]

    for path in ["/api/manifest", "/api/kline/manifest"]:
        sent = {}
        handler = object.__new__(handler_class)
        handler.path = path
        handler._send_json = lambda payload, status=None: sent.update(payload=payload)

        handler.do_GET()

        assert sent["payload"] == {"window": 321}

    for path in [
        "/api/bars?source_id=bitget&symbol=BTC%2FUSDT&frequency=1d",
        "/api/kline/bars?source_id=bitget&symbol=BTC%2FUSDT&frequency=1d",
    ]:
        sent = {}
        handler = object.__new__(handler_class)
        handler.path = path
        handler._send_json = lambda payload, status=None: sent.update(payload=payload)

        handler.do_GET()

        assert sent["payload"] == {"source_id": "bitget", "symbol": "BTC/USDT"}


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


def test_workbench_server_serves_kline_route_with_query_default_selection(monkeypatch):
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

    def fake_render_kline_viewer_html(payload):
        captured["kline_payload"] = payload
        return "kline shell"

    monkeypatch.setattr(workbench_server, "KlineCacheService", FakeKlineService)
    monkeypatch.setattr(workbench_server, "StrategyResultsService", FakeStrategyService)
    monkeypatch.setattr(workbench_server, "ThreadingHTTPServer", FakeServer)
    monkeypatch.setattr(workbench_server, "render_kline_viewer_html", fake_render_kline_viewer_html)

    workbench_server.serve_chart_workbench(
        kline_sources=[],
        results_roots=[],
        bars_root=".",
        default_window_size=321,
        data_api_base_url="http://data-host:8768/",
        data_api_token="viewer-token",
    )
    handler = object.__new__(captured["handler_class"])
    handler.path = "/kline?source_id=a_share&symbol=000001.SZ&frequency=1d"
    sent = {}
    handler._send_bytes = lambda body, content_type, status=None: sent.update(
        body=body,
        content_type=content_type,
    )

    handler.do_GET()

    assert sent["content_type"] == "text/html; charset=utf-8"
    assert sent["body"] == b"kline shell"
    assert captured["kline_payload"] == {
        "mode": "dynamic",
        "default_window_size": 321,
        "links": {"workbench_home": "/"},
        "data_api_base_url": "http://data-host:8768",
        "data_api_token": "viewer-token",
        "default_source_id": "a_share",
        "default_symbol": "000001.SZ",
        "default_frequency": "1d",
    }
