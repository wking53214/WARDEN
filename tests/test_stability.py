"""docs/STABILITY_v1.md is held to the code: what it promises is there, and a new thing must be added to the page."""

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_cli_integration import rig  # noqa: E402,F401  (the real-CLI rig)

from warden import CONTRACT, cli  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
PAGE = (ROOT / "docs" / "STABILITY_v1.md").read_text(encoding="utf-8")


def _section(title):
    body = PAGE.split(f"## {title}", 1)[1]
    return re.split(r"\n## ", body, maxsplit=1)[0]


def _options_of(command, capsys):
    with pytest.raises(SystemExit):
        cli.main([command, "--help"])
    out = capsys.readouterr().out
    return {o for o in re.findall(r"--[a-z][a-z0-9-]*", out) if not o.endswith("-")} - {"--help"}


@pytest.mark.parametrize("command", ["tagteam", "keep", "chronicle", "audit"])
def test_every_option_the_page_lists_exists_and_every_option_is_listed(command, capsys):
    line = next(l for ln in _section("1. The command line").splitlines() if ln.startswith(f"- `{command}`"))
    listed = set(re.findall(r"`(--[a-z][a-z0-9-]*)`", line))
    real = _options_of(command, capsys)
    assert listed == real, (sorted(listed - real), sorted(real - listed))


def test_the_page_names_exactly_the_commands_there_are():
    line = next(l for ln in _section("1. The command line").splitlines() if ln.startswith("Warden has four commands"))
    assert set(re.findall(r"`(\w+)`", line)) == {"tagteam", "keep", "chronicle", "audit"}


def test_the_exit_code_page_the_promise_points_at_is_the_codes_the_code_has():
    text = (ROOT / "docs" / "EXIT_CODES.md").read_text(encoding="utf-8")
    for decision, code in cli.EXIT_CODES.items():
        assert re.search(rf"^\| {code} \|.*`{decision}`", text, re.M), decision
    assert cli.EXIT_CODES["ACCEPT"] == 0 and all(c != 0 for d, c in cli.EXIT_CODES.items() if d != "ACCEPT")
    assert "EXIT_CODES.md" in _section("2. The exit codes")


def test_the_record_fields_the_page_lists_are_the_fields_a_real_run_prints(rig):
    code, payload, _ = rig.run()
    listed = set(re.findall(r"`(\w+)`", _section("3. The run record").split("Not promised")[0]))
    assert payload["schema"] == "cns.run/1" and "`cns.run/1`" in PAGE
    assert listed - {"cns.run/1"} <= set(payload), sorted(listed - set(payload))
    assert set(payload) - listed <= set(), f"add to the page: {sorted(set(payload) - listed)}"


def test_the_contract_number_the_page_names_is_the_code_s():
    assert f'`"{CONTRACT}"`' in _section("4. The seat contract")
    assert f'requires_contract = "{CONTRACT}"' in _section("4. The seat contract")
