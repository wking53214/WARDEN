"""From 0.20.0 `warden tagteam` isolates seats and the target's suite unless `--no-isolation` says otherwise."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_cli_integration import rig  # noqa: E402,F401  (the real-CLI rig)

from warden import cli, sandbox  # noqa: E402

pytestmark = pytest.mark.isolation_default

needs_limits = pytest.mark.skipif(sandbox.unavailable() is not None, reason="this machine cannot give the limits")


def test_the_shipped_default_is_on():
    assert cli.ISOLATE_BY_DEFAULT is True


@needs_limits
def test_a_named_seat_runs_isolated_with_no_flag_at_all(rig):
    code, payload, _ = rig.run(default_isolation=True)
    assert code == 3 and payload["decision"] == "ACCEPT_UNVERIFIED", payload["reason"]  # no instruments here
    assert payload["versions"]["seats"]["judge"].get("isolated") is True
    assert payload["versions"]["seats"]["drafter"].get("isolated") is True


def test_no_isolation_runs_in_process_and_says_so(rig):
    code, payload, err = rig.run("--no-isolation", default_isolation=True)
    assert code == 3 and payload["decision"] == "ACCEPT_UNVERIFIED", payload["reason"]  # no instruments here
    assert "isolated" not in payload["versions"]["seats"]["judge"]
    assert "--no-isolation" in err


def test_asking_for_both_is_a_usage_error_and_nothing_runs(rig):
    code, payload, _ = rig.run("--isolate-seats", "--no-isolation", default_isolation=True)
    assert code == 2 and payload["decision"] == "USAGE_ERROR"
