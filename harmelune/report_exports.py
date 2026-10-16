from __future__ import annotations

import csv
import html
import json
import re
from pathlib import Path
from typing import Any

_PATH_PATTERN = re.compile(r"(?<![A-Za-z0-9])(?:[A-Za-z]:/|/)[^\s,;<>\"']+")


def _safe_cell(value: Any, redact_paths: bool) -> str:
    text = str(value)
    if redact_paths:
        text = _PATH_PATTERN.sub("[path]", text)
    # Spreadsheet programs may evaluate cells beginning with formula markers.
    if text.lstrip().startswith(("=", "+", "-", "@")):
        text = "'" + text
    return text


def _rows(report: Any, redact_paths: bool) -> list[tuple[str, str, str]]:
    data = report.to_dict()
    rows: list[tuple[str, str, str]] = []
    for key in ("mode", "final_status", "planned", "attempted", "succeeded", "failed", "skipped", "rolled_back"):
        rows.append(("summary", key, _safe_cell(data.get(key, ""), redact_paths)))
    for key in ("copied", "replaced", "deleted", "conflicts", "errors", "backups", "rollback_failures"):
        for index, item in enumerate(data.get(key, []) or [], start=1):
            rows.append((key, str(index), _safe_cell(item, redact_paths)))
    return rows


def save_csv(report: Any, destination: str | Path, *, redact_paths: bool = False) -> Path:
    """Export report summary and file-level outcomes to spreadsheet-safe CSV."""
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(("section", "item", "value"))
        writer.writerows(_rows(report, redact_paths))
    return destination


def save_html(report: Any, destination: str | Path, *, redact_paths: bool = False) -> Path:
    """Write a self-contained HTML report with all untrusted values escaped."""
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    rows = _rows(report, redact_paths)
    body = "\n".join(
        "<tr><td>{}</td><td>{}</td><td>{}</td></tr>".format(
            html.escape(section), html.escape(item), html.escape(value)
        )
        for section, item, value in rows
    )
    status = html.escape(str(report.final_status.value if hasattr(report.final_status, "value") else report.final_status))
    document = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Harmelune operation report</title>
<style>
:root {{ color-scheme: dark; font-family: system-ui, sans-serif; background: #10131b; color: #e8eaf2; }}
body {{ max-width: 1100px; margin: 2rem auto; padding: 0 1rem; }}
h1 {{ color: #c5b9ff; }} .status {{ padding: .25rem .6rem; border: 1px solid #777; border-radius: .5rem; }}
table {{ border-collapse: collapse; width: 100%; }} th, td {{ text-align: left; padding: .6rem; border-bottom: 1px solid #343948; overflow-wrap: anywhere; }}
th {{ color: #c5b9ff; }}
</style>
</head>
<body>
<h1>Harmelune operation report</h1>
<p>Status: <strong class="status">{status}</strong></p>
<table><thead><tr><th>Section</th><th>Item</th><th>Value</th></tr></thead><tbody>
{body}
</tbody></table>
</body>
</html>
"""
    destination.write_text(document, encoding="utf-8")
    return destination


def export_report(report: Any, destination: str | Path, *, redact_paths: bool = False) -> Path:
    destination = Path(destination)
    suffix = destination.suffix.lower()
    if suffix == ".csv":
        return save_csv(report, destination, redact_paths=redact_paths)
    if suffix in {".html", ".htm"}:
        return save_html(report, destination, redact_paths=redact_paths)
    if suffix == ".json":
        return report.save_json(destination)
    raise ValueError(f"Unsupported report extension: {suffix or '(none)'}")
