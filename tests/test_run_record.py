"""Warden's printed run records are cns.run/1 records, whatever ended the run."""
from __future__ import annotations

import json

from warden import cli


def test_an_early_stop_is_a_complete_run_record(capsys):
    assert cli._stop("USAGE_ERROR", "no folder") == 2
    record = json.loads(capsys.readouterr().out)
    assert record["schema"] == "cns.run/1" and record["reason"] == "no folder"
    for key in ("contract", "converged", "finished", "put_back", "held_digest", "notes", "observed", "unmeasured"):
        assert key in record, key
    assert record["converged"] is False and record["finished"] is False and record["put_back"] is False


def test_a_usage_error_from_the_parser_is_a_complete_run_record(capsys):
    parser = cli._JsonParser(prog="warden")
    try:
        parser.error("bad option")
    except SystemExit as stop:
        assert stop.code == 2
    record = json.loads(capsys.readouterr().out)
    assert record["schema"] == "cns.run/1" and record["decision"] == "USAGE_ERROR"
    assert "bad option" in record["reason"] and record["converged"] is False


def test_the_contract_name_is_the_one_cns_defines():
    assert cli.CNS_RUN_SCHEMA == "cns.run/1"
