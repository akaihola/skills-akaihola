"""Exercise the ECB CLI without network access, using invented observations."""

import runpy
import sys
import urllib.request
from pathlib import Path
from unittest.mock import Mock

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "fetch_ecb_rates.py"
FIXTURE = Path(__file__).parent / "fixtures/rates.xml"


@pytest.fixture(autouse=True)
def block_network(monkeypatch):
    """Fail if a test unexpectedly tries to fetch real rates."""
    fetch = Mock(side_effect=AssertionError("live network access is forbidden"))
    monkeypatch.setattr(urllib.request, "urlopen", fetch)
    return fetch


@pytest.mark.parametrize(
    ("arguments", "status"), [(["--help"], 0), (["not-a-year"], 2)]
)
def test_cli_exits_before_fetch(monkeypatch, capsys, block_network, arguments, status):
    """Help and invalid years exit through argparse without fetching."""
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), *arguments])
    with pytest.raises(SystemExit) as error:
        runpy.run_path(str(SCRIPT), run_name="__main__")
    assert error.value.code == status
    block_network.assert_not_called()
    output = capsys.readouterr()
    assert "YEAR" in output.out + output.err


@pytest.mark.parametrize(
    ("arguments", "filename", "expected"),
    [
        ([], "valuuttakurssit_2025.csv", "date,rate\n02.01.2025,1.2\n03.01.2025,1.5\n"),
        (["2024", "chosen.csv"], "chosen.csv", "date,rate\n31.12.2024,1.25\n"),
        (["2023"], "valuuttakurssit_2023.csv", "date,rate\n"),
    ],
)
def test_cli_exports_fixture(monkeypatch, tmp_path, arguments, filename, expected):
    """Filter the year and currency, sort dates, and honor output/default paths."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), *arguments])
    with FIXTURE.open("rb") as response:
        fetch = Mock(return_value=response)
        monkeypatch.setattr(urllib.request, "urlopen", fetch)
        runpy.run_path(str(SCRIPT), run_name="__main__")
    assert (tmp_path / filename).read_text() == expected
    fetch.assert_called_once()
