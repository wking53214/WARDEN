"""Released seats: a pinned manifest may leave out `drafter` and `burnish`, and only the manifest and the folder
agreeing can do it.

Without `--stack-manifest`, `--stack` still needs all six checkouts. With one, ghost_tools, swizzle, assay and judge
must be named by the manifest and present; `drafter` and `burnish` are releasable. A seat is absent only when the
manifest does not name it and the folder does not hold it, and the run says so (`released_seats`, a note). A stack with
no drafter needs a proposer: the claim seat or an explicit `--drafter`.
"""

from __future__ import annotations

import sys
import textwrap

import pytest

from test_stack_option import _git_stack, _manifest, _repo, _run, _stack, measured  # noqa: F401 - measured is a fixture

SIX = ("ghost_tools", "swizzle", "assay", "drafter", "judge", "burnish")

CLAIM = textwrap.dedent("""\
    diff --git a/NOTE.md b/NOTE.md
    --- a/NOTE.md
    +++ b/NOTE.md
    @@ -1 +1 @@
    -old
    +claimed
    """)


def _claim_args(tmp_path):
    diff = tmp_path / "claim.diff"
    diff.write_text(CLAIM, encoding="utf-8")
    return ["--claim-diff", diff, "--claim-subject", "Step 1: say it", "--claim-author", "Ada <ada@example.org>"]


def _released_stack(tmp_path, absent=(), manifest_omit=(), manifest_extra=None):
    """A git stack folder without the `absent` checkouts, and a manifest naming every checkout it holds except
    `manifest_omit` (plus `manifest_extra`, a name to commit map, for a name the folder lacks)."""
    names = [n for n in SIX if n not in absent]
    stack = _stack(tmp_path / "stack", names=names)
    for child in stack.iterdir():
        (child / ".gitignore").write_text("__pycache__/\n", encoding="utf-8")
    commits = _git_stack(stack)
    repos = {k: v for k, v in commits.items() if k not in manifest_omit}
    repos.update(manifest_extra or {})
    return stack, _manifest(tmp_path, repos)


def _go(tmp_path, capsys, stack, manifest, *extra, target=None):
    target = target or _repo(tmp_path / "proj")
    args = ["--stack", stack, "--authorize", "w", "--reason", "r", *extra]
    if manifest is not None:
        args += ["--stack-manifest", manifest]
    code, payload, err = _run(capsys, target, *args)
    return code, payload, err, target


def _untouched(target):
    assert (target / "NOTE.md").read_text(encoding="utf-8") == "old\n"
    assert (target / "README.md").read_text(encoding="utf-8") == "# d\n"


# -- the strict default is unchanged ---------------------------------------------------------------------------

@pytest.mark.parametrize("missing", SIX)
def test_without_a_manifest_each_of_the_six_missing_is_a_usage_error_naming_it(tmp_path, capsys, measured, missing):  # noqa: F811
    stack = _stack(tmp_path / "stack", names=[n for n in SIX if n != missing])
    code, payload, err, target = _go(tmp_path, capsys, stack, None, *_claim_args(tmp_path))
    assert code == 2 and payload["decision"] == "USAGE_ERROR", err
    assert f"has no {missing} checkout" in payload["reason"] and payload["reason"].endswith("Nothing was run.")
    _untouched(target)


def test_a_full_stack_with_a_manifest_releases_nothing(tmp_path, capsys, measured):  # noqa: F811
    stack, manifest = _released_stack(tmp_path)
    code, payload, err, target = _go(tmp_path, capsys, stack, manifest)
    assert code in (0, 3), (payload["reason"], err)
    assert payload["released_seats"] == []
    assert not any(n.startswith("released seats") for n in payload["notes"])
    assert payload["versions"]["seats"]["finisher"]["spec"] == "burnish.finisher:Burnish"
    assert payload["evidence"]["finisher_ran"] is True


# -- a seat the manifest and the folder agree is absent ---------------------------------------------------------

def test_burnish_alone_may_be_released_and_the_run_has_no_finisher(tmp_path, capsys, measured):  # noqa: F811
    stack, manifest = _released_stack(tmp_path, absent=("burnish",))
    code, payload, err, target = _go(tmp_path, capsys, stack, manifest)
    assert code in (0, 3), (payload["reason"], err)
    assert payload["released_seats"] == ["burnish"]
    assert any(n.startswith("released seats not seated: burnish") for n in payload["notes"])
    assert payload["versions"]["seats"]["finisher"] is None
    assert payload["evidence"]["finisher_ran"] is False and payload["finished"] is False
    names = [p["name"] for p in payload["claim"]["participants"]]
    assert "finisher seat" not in names and "drafter seat" in names and "judge seat" in names
    assert payload["claim"]["finisher_edits"] == []
    assert (target / "README.md").read_text(encoding="utf-8") == "# d\n"  # nothing finished the README
    assert "burnish" not in sys.modules


def test_drafter_alone_may_be_released_when_a_claim_proposes(tmp_path, capsys, measured):  # noqa: F811
    stack, manifest = _released_stack(tmp_path, absent=("drafter",))
    code, payload, err, target = _go(tmp_path, capsys, stack, manifest, *_claim_args(tmp_path))
    assert code in (0, 3), (payload["reason"], err)
    assert payload["released_seats"] == ["drafter"]
    note = next(n for n in payload["notes"] if n.startswith("released seats not seated: drafter"))
    assert "claim seat" in note
    assert payload["versions"]["seats"]["drafter"]["spec"] == "warden.claim:ClaimDrafter"
    assert payload["versions"]["seats"]["finisher"]["spec"] == "burnish.finisher:Burnish"
    assert payload["claim"]["claimed_subject"] == "Step 1: say it"
    assert "drafter" not in sys.modules and "drafter.seat" not in sys.modules


def test_both_may_be_released_and_both_are_recorded(tmp_path, capsys, measured):  # noqa: F811
    stack, manifest = _released_stack(tmp_path, absent=("drafter", "burnish"))
    code, payload, err, target = _go(tmp_path, capsys, stack, manifest, *_claim_args(tmp_path))
    assert code in (0, 3), (payload["reason"], err)
    assert payload["released_seats"] == ["burnish", "drafter"]
    assert any(n.startswith("released seats not seated: burnish, drafter") for n in payload["notes"])
    assert payload["versions"]["seats"]["finisher"] is None
    assert payload["evidence"]["finisher_ran"] is False
    names = [p["name"] for p in payload["claim"]["participants"]]
    assert "finisher seat" not in names and "judge seat" in names


def test_cns_as_the_manifest_releases_the_same_way(tmp_path, capsys, measured):  # noqa: F811
    stack, manifest = _released_stack(tmp_path, absent=("burnish",))
    cns = tmp_path / "cns"
    (cns / "contracts").mkdir(parents=True)
    manifest.rename(cns / "contracts" / "warden-stack.json")
    target = _repo(tmp_path / "proj")
    code, payload, err = _run(capsys, target, "--stack", stack, "--cns", cns, "--authorize", "w", "--reason", "r")
    assert code in (0, 3), (payload["reason"], err)
    assert payload["released_seats"] == ["burnish"]


# -- a stack without a drafter needs a proposer -------------------------------------------------------------------

def test_a_stack_without_a_drafter_and_without_a_proposer_is_a_usage_error(tmp_path, capsys, measured):  # noqa: F811
    stack, manifest = _released_stack(tmp_path, absent=("drafter",))
    code, payload, err, target = _go(tmp_path, capsys, stack, manifest)
    assert code == 2 and payload["decision"] == "USAGE_ERROR", err
    assert ("this stack has no drafter and nothing to propose; give --claim-commit, --claim-diff or --drafter"
            in payload["reason"])
    assert payload["reason"].endswith("Nothing was run.")
    _untouched(target)


# -- the other four cannot be released -------------------------------------------------------------------------

@pytest.mark.parametrize("seat", ["ghost_tools", "swizzle", "assay", "judge"])
def test_the_instruments_and_the_judge_cannot_be_released(tmp_path, capsys, measured, seat):  # noqa: F811
    # absent from the folder and from the manifest: still a usage error naming it
    stack, manifest = _released_stack(tmp_path, absent=(seat,))
    code, payload, err, target = _go(tmp_path, capsys, stack, manifest)
    assert code == 2 and payload["decision"] == "USAGE_ERROR", err
    assert f"has no {seat} checkout" in payload["reason"]
    _untouched(target)


@pytest.mark.parametrize("seat", ["ghost_tools", "swizzle", "assay", "judge"])
def test_a_manifest_that_omits_one_of_the_four_is_refused_as_before(tmp_path, capsys, measured, seat):  # noqa: F811
    stack, manifest = _released_stack(tmp_path, manifest_omit=(seat,))
    code, payload, err, target = _go(tmp_path, capsys, stack, manifest)
    assert code == 2 and payload["decision"] == "USAGE_ERROR", err
    assert f"does not name {seat!r}" in payload["reason"] and payload["reason"].endswith("Nothing was run.")
    _untouched(target)


# -- disagreement between the manifest and the folder is refused -------------------------------------------------

@pytest.mark.parametrize("seat", ["burnish", "drafter"])
def test_a_folder_holding_a_seat_the_manifest_omits_is_refused_as_unnamed(tmp_path, capsys, measured, seat):  # noqa: F811
    stack, manifest = _released_stack(tmp_path, manifest_omit=(seat,))
    code, payload, err, target = _go(tmp_path, capsys, stack, manifest)
    assert code == 2 and payload["decision"] == "USAGE_ERROR", err
    assert f"does not name {seat!r} (the checkout at" in payload["reason"]
    assert payload["reason"].endswith("Nothing was run.")
    _untouched(target)


@pytest.mark.parametrize("seat", ["burnish", "drafter"])
def test_a_manifest_naming_a_seat_the_folder_lacks_is_refused(tmp_path, capsys, measured, seat):  # noqa: F811
    stack, manifest = _released_stack(tmp_path, absent=(seat,), manifest_extra={seat: "1" * 40})
    code, payload, err, target = _go(tmp_path, capsys, stack, manifest, *_claim_args(tmp_path))
    assert code == 2 and payload["decision"] == "USAGE_ERROR", err
    assert f"has no {seat} checkout" in payload["reason"] and payload["reason"].endswith("Nothing was run.")
    _untouched(target)


def test_an_unreadable_manifest_releases_nothing(tmp_path, capsys, measured):  # noqa: F811
    stack = _stack(tmp_path / "stack", names=[n for n in SIX if n != "burnish"])
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    code, payload, err, target = _go(tmp_path, capsys, stack, bad)
    assert code == 2 and "has no burnish checkout" in payload["reason"]
    _untouched(target)


# -- an explicit option still wins ------------------------------------------------------------------------------

def _module(tmp_path, monkeypatch, name, source):
    seats = tmp_path / "seats"
    seats.mkdir(exist_ok=True)
    (seats / f"{name}.py").write_text(source, encoding="utf-8")
    monkeypatch.syspath_prepend(str(seats))
    sys.modules.pop(name, None)


EXPLICIT_FINISHER = '''
from pathlib import Path
from warden.models import FileEdit, Transformation, TransformationStatus


class Finisher:
    requires_contract = "1"

    def finish(self, target, baseline, facts):
        old = (Path(target) / "README.md").read_text(encoding="utf-8")
        return Transformation(
            target=str(Path(target).resolve()), intent="explicit finisher", architectural_reason="test",
            affected_files=("README.md",), expected_behavior="none", preservation_requirements=(),
            known_defects=(), transformation_scope="documentation", baseline_reference=baseline,
            evidence=(), edits=(FileEdit(path="README.md", kind="write", new="explicitly finished\\n", old=old),),
            status=TransformationStatus.PROPOSED)
'''

EXPLICIT_DRAFTER = '''
from pathlib import Path
from warden.models import FileEdit, Transformation, TransformationStatus


class Drafter:
    requires_contract = "1"

    def __init__(self):
        self.done = False

    def propose(self, target, observed, baseline):
        if self.done:
            return None
        self.done = True
        old = (Path(target) / "NOTE.md").read_text(encoding="utf-8")
        return Transformation(
            target=str(Path(target).resolve()), intent="explicit drafter", architectural_reason="test",
            affected_files=("NOTE.md",), expected_behavior="none", preservation_requirements=(),
            known_defects=(), transformation_scope="documentation", baseline_reference=baseline,
            evidence=(), edits=(FileEdit(path="NOTE.md", kind="write", new="explicitly drafted\\n", old=old),),
            status=TransformationStatus.PROPOSED)
'''


def test_an_explicit_finisher_wins_over_a_released_burnish(tmp_path, capsys, measured, monkeypatch):  # noqa: F811
    _module(tmp_path, monkeypatch, "explicit_finisher", EXPLICIT_FINISHER)
    stack, manifest = _released_stack(tmp_path, absent=("burnish",))
    code, payload, err, target = _go(tmp_path, capsys, stack, manifest, "--finisher", "explicit_finisher:Finisher")
    sys.modules.pop("explicit_finisher", None)
    assert code in (0, 3), (payload["reason"], err)
    assert payload["versions"]["seats"]["finisher"]["spec"] == "explicit_finisher:Finisher"
    assert (target / "README.md").read_text(encoding="utf-8") == "explicitly finished\n"
    assert payload["evidence"]["finisher_ran"] is True
    assert payload["released_seats"] == ["burnish"]
    note = next(n for n in payload["notes"] if n.startswith("released seats not seated"))
    assert "explicit --finisher" in note and "no finisher" not in note


def test_an_explicit_drafter_wins_over_a_released_drafter(tmp_path, capsys, measured, monkeypatch):  # noqa: F811
    _module(tmp_path, monkeypatch, "explicit_drafter", EXPLICIT_DRAFTER)
    stack, manifest = _released_stack(tmp_path, absent=("drafter",))
    code, payload, err, target = _go(tmp_path, capsys, stack, manifest, "--drafter", "explicit_drafter:Drafter")
    sys.modules.pop("explicit_drafter", None)
    assert code in (0, 3), (payload["reason"], err)
    assert payload["versions"]["seats"]["drafter"]["spec"] == "explicit_drafter:Drafter"
    assert payload["released_seats"] == ["drafter"]
    note = next(n for n in payload["notes"] if n.startswith("released seats not seated"))
    assert "explicit --drafter" in note
    names = [p["name"] for p in payload["claim"]["participants"]]
    assert "drafter seat" in names
