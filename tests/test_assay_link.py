"""ASSAY -> Warden: the answer key arrives, or the run says why it did not.

The original adapter returned [] when the registry file was missing, which is
indistinguishable from "ASSAY has no specimens". These tests pin the
loud behaviour, and the last one reads the real ASSAY checkout when
ASSAY_ROOT points at one.
"""
import json
import os
from pathlib import Path

import pytest

from warden.horsemen import HorsemenWorkflow, AssayAdapter, AssayUnavailable
from warden.horsemen.authorization_scope import ChangeClass


def _corpus(root: Path, entries: dict) -> Path:
    (root / "assay_production").mkdir(parents=True)
    (root / "specimens").mkdir()
    (root / "specimens" / "a.py").write_text("x = 1\n", encoding="utf-8")
    reg = root / "assay_production" / "registry.json"
    reg.write_text(json.dumps(entries), encoding="utf-8")
    return reg


GOOD = {"a": {"specimen_id": "a", "specimen_class": "REFERENCE", "path": "specimens/a.py",
              "expected_verdict": "ACCEPT", "epistemic_status": "RECORDED_IN_MANIFEST"}}


def test_no_root_is_an_error_not_an_empty_list():
    with pytest.raises(AssayUnavailable):
        AssayAdapter().load_registry()


def test_missing_registry_is_an_error(tmp_path: Path):
    with pytest.raises(AssayUnavailable, match="not found"):
        AssayAdapter(tmp_path).load_registry()


def test_empty_registry_is_an_error(tmp_path: Path):
    _corpus(tmp_path, {})
    with pytest.raises(AssayUnavailable, match="empty"):
        AssayAdapter(tmp_path).load_registry()


def test_registry_naming_a_missing_file_is_an_error(tmp_path: Path):
    _corpus(tmp_path, {"b": dict(GOOD["a"], specimen_id="b", path="specimens/nope.py")})
    with pytest.raises(AssayUnavailable, match="do not exist"):
        AssayAdapter(tmp_path).load_registry()


def test_good_registry_loads_and_hands_off(tmp_path: Path):
    _corpus(tmp_path, GOOD)
    specs = AssayAdapter(tmp_path).load_registry()
    assert [s.expected_verdict for s in specs] == ["ACCEPT"]
    wf = HorsemenWorkflow(assay=AssayAdapter(tmp_path))
    st = wf.start(repository="demo", baseline_id="b0", baseline_sha="0" * 40,
                  change_class=ChangeClass.DOCUMENTATION_ONLY)
    hof = wf.ingest_specimens(st.workflow_id, specs)
    assert hof.result == "SPECIMENS_PROVIDED"
    assert st.phases[-1].result == "SPECIMENS_PROVIDED"


def test_empty_specimen_handoff_is_unknown_not_ok(tmp_path: Path):
    wf = HorsemenWorkflow(assay=AssayAdapter(tmp_path))
    st = wf.start(repository="demo", baseline_id="b0", baseline_sha="0" * 40,
                  change_class=ChangeClass.DOCUMENTATION_ONLY)
    hof = wf.ingest_specimens(st.workflow_id, [])
    assert hof.result == "NO_SPECIMENS_UNKNOWN"
    assert st.phases[-1].result != "ok"


@pytest.mark.skipif(not os.environ.get("ASSAY_ROOT"),
                    reason="set ASSAY_ROOT to an ASSAY checkout to run the live link")
def test_live_assay_registry():
    specs = AssayAdapter(os.environ["ASSAY_ROOT"]).load_registry()
    by_id = {s.specimen_id: s for s in specs}
    # MANIFEST.md section 3.1: the silent pass must be refused.
    assert by_id["fm_3_1_silent_pass"].expected_verdict == "REFUSE"
    classes = {s.specimen_class for s in specs}
    assert {"RECONSTRUCTION_PAIR", "FAILURE_MODE", "REFERENCE", "SUPERSEDED"} <= classes
