"""CLI regression tests for Phase 3 contract hardening."""

import json
import subprocess
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
CLI_PATH = ROOT_DIR / "src_cli.py"
FIXTURE_PATH = ROOT_DIR / "tests" / "fixtures" / "cli_sample.csv"


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    """Run CLI command with subprocess for black-box verification."""
    return subprocess.run(
        [sys.executable, str(CLI_PATH), *args],
        capture_output=True,
        text=True,
        cwd=ROOT_DIR,
    )


def test_cli_help() -> None:
    """CLI help should expose required usage contract."""
    result = run_cli("--help")

    assert result.returncode == 0
    assert "usage:" in result.stdout.lower()
    assert "csv_file" in result.stdout
    assert "--output" in result.stdout


def test_cli_missing_file() -> None:
    """CLI should fail fast when given a missing file path."""
    result = run_cli("missing.csv")

    assert result.returncode == 1
    assert "Error: File not found" in result.stderr


def test_cli_output_json_contract(tmp_path: Path) -> None:
    """CLI should produce JSON with stable root and recommendation keys."""
    output_path = tmp_path / "cli-output.json"

    result = run_cli(str(FIXTURE_PATH), "--output", str(output_path))

    assert result.returncode == 0
    assert output_path.exists()

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert set(payload.keys()) == {"activities", "mappings", "recommendations", "statistics"}

    assert payload["recommendations"]
    recommendation = payload["recommendations"][0]
    for key in [
        "inferred_activity",
        "events",
        "execution_environment",
        "method",
        "method_category",
        "confidence",
    ]:
        assert key in recommendation
