from backtest.charts.workbench_server import render_workbench_index_html


def test_render_workbench_index_html_links_both_chart_apps():
    html = render_workbench_index_html()

    assert "Backtest Workbench" in html
    assert 'href="/strategy-results"' in html
    assert "Strategy Results" in html
    assert 'href="/kline"' in html
    assert "K-line Viewer" in html
