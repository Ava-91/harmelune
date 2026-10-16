from __future__ import annotations

import csv
from pathlib import Path

from harmelune.execution_report import ExecutionReport, ReportStatus
from harmelune.report_exports import export_report, save_csv, save_html


def make_report() -> ExecutionReport:
    return ExecutionReport(
        mode="safe",
        final_status=ReportStatus.PARTIAL,
        planned=2,
        attempted=2,
        succeeded=1,
        failed=1,
        copied=["C:/Users/Ava/Music/song.flac -> D:/Music/song.flac"],
        errors=["Bad tag: <script>alert(1)</script>"],
    )


def test_csv_contains_summary_and_outcomes_and_redacts_paths(tmp_path: Path):
    target = save_csv(make_report(), tmp_path / "report.csv", redact_paths=True)
    text = target.read_text(encoding="utf-8-sig")
    assert "summary,mode,safe" in text
    assert "copied" in text
    assert "[path]" in text
    assert "C:/Users/Ava" not in text


def test_csv_neutralizes_formula_injection(tmp_path: Path):
    report = ExecutionReport(
        mode="safe",
        final_status=ReportStatus.SUCCESS,
        errors=["=HYPERLINK(\"https://example.invalid\",\"click\")"],
    )
    target = save_csv(report, tmp_path / "report.csv")
    with target.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.reader(handle))
    assert any(row[0] == "errors" and row[2].startswith("'=") for row in rows)


def test_html_escapes_metadata_and_is_self_contained(tmp_path: Path):
    target = save_html(make_report(), tmp_path / "report.html")
    content = target.read_text(encoding="utf-8")
    assert "<script>alert(1)</script>" not in content
    assert "&lt;script&gt;" in content
    assert "Harmelune operation report" in content
    assert "https://" not in content


def test_export_dispatch_and_json_compatibility(tmp_path: Path):
    report = make_report()
    csv_path = export_report(report, tmp_path / "out.csv")
    html_path = export_report(report, tmp_path / "out.html")
    json_path = export_report(report, tmp_path / "out.json")
    assert csv_path.is_file() and html_path.is_file() and json_path.is_file()
    assert '"final_status": "PARTIAL"' in json_path.read_text(encoding="utf-8")
