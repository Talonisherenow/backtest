from html import escape
from typing import Any


def _format_value(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.6g}"
    return str(value)


def _render_rows(payload: dict[str, Any]) -> str:
    rows = []
    for key, value in payload.items():
        rows.append(
            "<tr>"
            f"<th>{escape(str(key))}</th>"
            f"<td>{escape(_format_value(value))}</td>"
            "</tr>"
        )
    return "\n".join(rows)


def render_html_report(title: str, metrics: dict[str, Any], manifest: dict[str, Any]) -> str:
    escaped_title = escape(title)
    metrics_rows = _render_rows(metrics)
    manifest_rows = _render_rows(manifest)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>{escaped_title}</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 2rem; color: #1f2937; }}
    h1 {{ margin-bottom: 0.25rem; }}
    section {{ margin-top: 1.5rem; }}
    table {{ border-collapse: collapse; min-width: 28rem; }}
    th, td {{ border: 1px solid #d1d5db; padding: 0.5rem 0.75rem; text-align: left; }}
    th {{ background: #f3f4f6; }}
  </style>
</head>
<body>
  <h1>{escaped_title}</h1>
  <section>
    <h2>核心指标</h2>
    <table>
      <tbody>
{metrics_rows}
      </tbody>
    </table>
  </section>
  <section>
    <h2>运行信息</h2>
    <table>
      <tbody>
{manifest_rows}
      </tbody>
    </table>
  </section>
</body>
</html>
"""
