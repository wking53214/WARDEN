"""A typed name is not a verified human.

Alan's review (2026-11) approved a change as "Claude Code agent" and the receipt read
`authority_source: human_operator`. These tests hold that closed: the label says human only when someone
answered a fresh challenge on a terminal, and without that a run can not reach APPROVED.
"""

import os
import pty
import re
import threading

import pytest

from warden import approval, ghost
from warden.authorization import grant
from warden.horsemen import receipt_for_run
from warden.tagteam import TagTeam

from fakes import FakeDrafter, FakeJudge
from test_assay_link import GOOD, _corpus
from test_honest_exit_codes import _proc, _repo
from test_horsemen_circuit import measured  # noqa: F401  (fixture)


def _answering_terminal(answer_for_code):
    """A pseudo-terminal whose far end reads the prompt, finds the code and types `answer_for_code(code)`."""
    master, slave = pty.openpty()
    path = os.ttyname(slave)

    def person():
        seen = b""
        while b"refuses:" not in seen:
            seen += os.read(master, 1024)
        text = seen.decode()
        code = re.search(r"approve ([0-9a-f]{6})", text).group(1)
        os.write(master, (answer_for_code(code) + "\n").encode())

    thread = threading.Thread(target=person, daemon=True)
    thread.start()
    return path, thread, (master, slave)


def test_with_no_terminal_nobody_is_verified(tmp_path):
    assert approval.confirm_on_terminal("william", "transform", "x", "r", tty_path=str(tmp_path / "no-such-tty")) == ""


def test_a_person_who_types_the_fresh_code_is_verified():
    path, thread, fds = _answering_terminal(lambda code: f"approve {code}")
    try:
        assert approval.confirm_on_terminal("william", "transform", "x", "r", tty_path=path) == approval.TERMINAL
    finally:
        thread.join(5)
        for fd in fds:
            os.close(fd)


@pytest.mark.parametrize("answer", [lambda c: "approve", lambda c: "yes", lambda c: "approve 000000x", lambda c: ""])
def test_any_other_answer_refuses(answer):
    path, thread, fds = _answering_terminal(answer)
    try:
        assert approval.confirm_on_terminal("william", "transform", "x", "r", tty_path=path) == ""
    finally:
        thread.join(5)
        for fd in fds:
            os.close(fd)


def test_a_typed_name_alone_never_claims_to_be_a_human():
    for name in ("william", "Claude Code agent", "Alan"):
        auth = grant(name, "transform", "/x", "code", "r")
        assert auth.verified_by == "" and auth.authority == "unverified_claim"
    assert grant("william", "transform", "/x", "code", "r", verified_by="terminal").authority == "human_operator"


def _receipt(tmp_path, actor, verified_by):
    target = _repo(tmp_path / "t")
    assay_root = tmp_path / "assay"
    _corpus(assay_root, GOOD)
    auth = grant(actor, "transform", str(target.resolve()), "documentation", "r", verified_by=verified_by)
    team = TagTeam(drafter=FakeDrafter(steps=("new\n",)), judge=FakeJudge("ACCEPT", ("fine",)),
                   ghost_tools_root=tmp_path, swizzle_root=tmp_path, assay_root=assay_root)
    result = team.run(target, findings=[], authorization=auth)
    return receipt_for_run(result=result, target=target, authorization=auth, baseline_sha="a" * 40,
                           assay_root=assay_root).to_dict()


def test_alans_exploit_an_agent_name_does_not_get_a_human_receipt_or_approval(tmp_path, measured):  # noqa: F811
    data = _receipt(tmp_path, "Claude Code agent", "")
    assert data["authority_source"] == "unverified_claim"
    assert data["final_verdict"] == "REQUIRES_HUMAN_REVIEW"          # not APPROVED
    assert any("not verified" in u for u in data["unknowns"])


def test_a_verified_approver_still_reaches_approved(tmp_path, measured):  # noqa: F811
    data = _receipt(tmp_path, "william", "terminal")
    assert data["authority_source"] == "human_operator" and data["final_verdict"] == "APPROVED"


def test_ghost_runs_with_secret_scanning_on(monkeypatch, tmp_path):
    seen = {}

    def fake(cmd, **kw):
        seen["cmd"] = list(cmd)
        return _proc("[]", "", 0)

    monkeypatch.setattr(ghost, "run_instrument", fake)
    try:
        ghost.scan(tmp_path, ghost_tools_root=tmp_path)
    except Exception:  # the fake's output may not satisfy every check; only the command line matters here
        pass
    assert seen["cmd"] and "--no-secrets" not in seen["cmd"]
