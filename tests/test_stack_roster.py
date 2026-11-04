"""The circuit roster: a pinned manifest must name all five circuit members (ghost_tools, swizzle, assay, judge and
warden), and the warden checkout in the --stack folder is checked (pinned commit, clean) like the other four.

Before 0.16.5 a manifest that omitted warden was accepted with a dirty warden checkout (exit 0) while a manifest that
omitted any of the other four was refused. This is configuration integrity, the same kind of check as the refusals
for the other four members; it measures nothing about the change being governed.
"""

from __future__ import annotations

import pytest

from test_stack_option import _git_stack, _manifest, _repo, _run, _stack, measured  # noqa: F401 - measured is a fixture
from test_stack_released import _claim_args

CIRCUIT = ("ghost_tools", "swizzle", "assay", "judge", "warden")
SEATS = ("drafter", "burnish")


def _roster_stack(tmp_path, absent=(), manifest_omit=()):
    """A git stack folder holding every circuit member and both releasable seats except `absent`, and a manifest
    naming every checkout it holds except `manifest_omit`."""
    names = [n for n in (*CIRCUIT[:4], "drafter", "burnish", "warden") if n not in absent]
    stack = _stack(tmp_path / "stack", names=names)
    for child in stack.iterdir():
        (child / ".gitignore").write_text("__pycache__/\n", encoding="utf-8")
    commits = _git_stack(stack)
    repos = {k: v for k, v in commits.items() if k not in manifest_omit}
    return stack, _manifest(tmp_path, repos)


def _go(tmp_path, capsys, stack, manifest, *extra):
    target = _repo(tmp_path / "proj")
    code, payload, err = _run(capsys, target, "--stack", stack, "--stack-manifest", manifest, "--authorize", "w",
                              "--reason", "r", *extra)
    return code, payload, err, target


def _untouched(target):
    assert (target / "NOTE.md").read_text(encoding="utf-8") == "old\n"


def _dirty(stack, name):
    (stack / name / "MARK.md").write_text("changed after the pin\n", encoding="utf-8")


def test_a_manifest_that_omits_warden_with_a_clean_checkout_is_refused(tmp_path, capsys, measured):  # noqa: F811
    stack, manifest = _roster_stack(tmp_path, manifest_omit=("warden",))
    code, payload, err, target = _go(tmp_path, capsys, stack, manifest)
    assert code == 2 and payload["decision"] == "USAGE_ERROR", (payload["reason"], err)
    assert "does not name 'warden'" in payload["reason"] and payload["reason"].endswith("Nothing was run.")
    _untouched(target)


def test_a_manifest_that_omits_warden_with_a_dirty_checkout_is_refused_naming_warden(tmp_path, capsys, measured):  # noqa: F811
    stack, manifest = _roster_stack(tmp_path, manifest_omit=("warden",))
    _dirty(stack, "warden")
    code, payload, err, target = _go(tmp_path, capsys, stack, manifest)
    assert code == 2 and payload["decision"] == "USAGE_ERROR", (payload["reason"], err)
    assert "does not name 'warden'" in payload["reason"] and payload["reason"].endswith("Nothing was run.")
    _untouched(target)


def test_a_manifest_that_omits_warden_is_refused_when_the_folder_has_no_warden_either(tmp_path, capsys, measured):  # noqa: F811
    stack, manifest = _roster_stack(tmp_path, absent=("warden",))
    code, payload, err, target = _go(tmp_path, capsys, stack, manifest)
    assert code == 2 and payload["decision"] == "USAGE_ERROR", (payload["reason"], err)
    assert "does not name 'warden'" in payload["reason"]
    _untouched(target)


def test_a_full_manifest_with_a_dirty_warden_is_refused(tmp_path, capsys, measured):  # noqa: F811
    stack, manifest = _roster_stack(tmp_path)
    _dirty(stack, "warden")
    code, payload, err, target = _go(tmp_path, capsys, stack, manifest)
    assert code == 2 and payload["decision"] == "USAGE_ERROR", (payload["reason"], err)
    assert repr(str(stack / "warden")) in payload["reason"] and "uncommitted changes" in payload["reason"]
    _untouched(target)


def test_a_full_manifest_with_a_warden_at_another_commit_is_refused(tmp_path, capsys, measured):  # noqa: F811
    from gitutil import commit_all
    stack, manifest = _roster_stack(tmp_path)
    _dirty(stack, "warden")
    commit_all(stack / "warden", "moved on")
    code, payload, err, target = _go(tmp_path, capsys, stack, manifest)
    assert code == 2 and payload["decision"] == "USAGE_ERROR", (payload["reason"], err)
    assert "pins 'warden'" in payload["reason"] and "is at" in payload["reason"]
    _untouched(target)


def test_a_full_manifest_with_clean_checkouts_runs(tmp_path, capsys, measured):  # noqa: F811
    stack, manifest = _roster_stack(tmp_path)
    code, payload, err, target = _go(tmp_path, capsys, stack, manifest)
    assert code in (0, 3), (payload["reason"], err)
    assert payload["released_seats"] == []


@pytest.mark.parametrize("member", CIRCUIT)
def test_a_manifest_that_omits_any_circuit_member_is_a_usage_error_naming_it(tmp_path, capsys, measured, member):  # noqa: F811
    stack, manifest = _roster_stack(tmp_path, manifest_omit=(member,))
    code, payload, err, target = _go(tmp_path, capsys, stack, manifest)
    assert code == 2 and payload["decision"] == "USAGE_ERROR", (payload["reason"], err)
    assert f"does not name {member!r}" in payload["reason"] and payload["reason"].endswith("Nothing was run.")
    _untouched(target)


@pytest.mark.parametrize("member", ["swizzle", "warden"])
def test_an_explicit_option_does_not_excuse_an_omitted_member(tmp_path, capsys, measured, member):  # noqa: F811
    """An explicit --swizzle-root stops the stack's own copy being used, but the roster is still the roster."""
    other = tmp_path / "other"
    other.mkdir()
    stack, manifest = _roster_stack(tmp_path, manifest_omit=(member,))
    extra = ("--swizzle-root", other) if member == "swizzle" else ()
    code, payload, err, target = _go(tmp_path, capsys, stack, manifest, *extra)
    assert code == 2 and payload["decision"] == "USAGE_ERROR", (payload["reason"], err)
    assert f"does not name {member!r}" in payload["reason"]
    _untouched(target)


def test_the_cns_hub_manifest_is_held_to_the_same_roster(tmp_path, capsys, measured):  # noqa: F811
    stack, manifest = _roster_stack(tmp_path, manifest_omit=("warden",))
    cns = tmp_path / "cns"
    (cns / "contracts").mkdir(parents=True)
    manifest.rename(cns / "contracts" / "warden-stack.json")
    target = _repo(tmp_path / "proj")
    code, payload, err = _run(capsys, target, "--stack", stack, "--cns", cns, "--authorize", "w", "--reason", "r")
    assert code == 2 and "does not name 'warden'" in payload["reason"], (payload["reason"], err)
    _untouched(target)


# -- the released seats rule is unchanged --------------------------------------------------------------------

def test_drafter_and_burnish_may_still_be_released_when_warden_is_named(tmp_path, capsys, measured):  # noqa: F811
    stack, manifest = _roster_stack(tmp_path, absent=SEATS)
    code, payload, err, target = _go(tmp_path, capsys, stack, manifest, *_claim_args(tmp_path))
    assert code in (0, 3), (payload["reason"], err)
    assert payload["released_seats"] == ["burnish", "drafter"]


@pytest.mark.parametrize("seat", SEATS)
def test_a_released_seat_the_manifest_omits_while_the_folder_holds_it_is_still_refused(tmp_path, capsys, measured, seat):  # noqa: F811
    stack, manifest = _roster_stack(tmp_path, manifest_omit=(seat,))
    code, payload, err, target = _go(tmp_path, capsys, stack, manifest)
    assert code == 2 and f"does not name {seat!r} (the checkout at" in payload["reason"], payload["reason"]
    _untouched(target)
