from warden.horsemen.authorization_scope import (
    ChangeClass,
    ScopeSpec,
    grant_scoped,
)


def make_grant(operations=("transform",), subjects=("/repo",),
               change_classes=("DOCUMENTATION_ONLY",)):
    scope = ScopeSpec(
        repository="example-repo",
        baseline_id="baseline-1",
        operations=operations,
        subjects=subjects,
        change_classes=change_classes,
    )
    return grant_scoped(
        actor="william",
        operation="transform",
        subject="/repo",
        scope=scope,
        change_class=ChangeClass.DOCUMENTATION_ONLY,
        proposal_id="proposal-1",
        reason="Scoped authorization regression test",
    )


def test_matching_grant_and_scope_are_permitted():
    grant = make_grant()
    assert grant.permits(
        "transform", "/repo", "baseline-1",
        ChangeClass.DOCUMENTATION_ONLY,
        repository="example-repo",
    )


def test_base_operation_cannot_override_scope_exclusion():
    grant = make_grant(operations=("read",))
    assert not grant.permits(
        "transform", "/repo", "baseline-1",
        ChangeClass.DOCUMENTATION_ONLY,
        repository="example-repo",
    )


def test_base_subject_cannot_override_scope_exclusion():
    grant = make_grant(subjects=("/repo/docs",))
    assert not grant.permits(
        "transform", "/repo", "baseline-1",
        ChangeClass.DOCUMENTATION_ONLY,
        repository="example-repo",
    )


def test_empty_allowlists_deny_access():
    for grant in (
        make_grant(operations=()),
        make_grant(subjects=()),
        make_grant(change_classes=()),
    ):
        assert not grant.permits(
            "transform", "/repo", "baseline-1",
            ChangeClass.DOCUMENTATION_ONLY,
            repository="example-repo",
        )


def test_wrong_baseline_is_denied():
    grant = make_grant()
    assert not grant.permits(
        "transform", "/repo", "other-baseline",
        ChangeClass.DOCUMENTATION_ONLY,
        repository="example-repo",
    )


def test_missing_change_class_is_denied():
    grant = make_grant()
    assert not grant.permits("transform", "/repo", "baseline-1", repository="example-repo")


def test_wrong_change_class_is_denied():
    grant = make_grant(
        change_classes=("DOCUMENTATION_ONLY", "TEST_ONLY")
    )
    assert not grant.permits(
        "transform", "/repo", "baseline-1",
        ChangeClass.TEST_ONLY,
        repository="example-repo",
    )


def test_matching_repository_is_permitted():
    grant = make_grant()
    assert grant.permits(
        "transform", "/repo", "baseline-1",
        ChangeClass.DOCUMENTATION_ONLY,
        repository="example-repo",
    )


def test_different_repository_is_denied():
    grant = make_grant()
    assert not grant.permits(
        "transform", "/repo", "baseline-1",
        ChangeClass.DOCUMENTATION_ONLY,
        repository="different-repo",
    )


def test_missing_repository_is_denied():
    grant = make_grant()
    assert not grant.permits(
        "transform", "/repo", "baseline-1",
        ChangeClass.DOCUMENTATION_ONLY,
    )


def test_workflow_rejects_repository_scope_mismatch_before_edit():
    import pytest

    from warden.horsemen import HorsemenWorkflow
    from warden.horsemen.authorization_scope import ScopeViolation

    wf = HorsemenWorkflow()
    st = wf.start(
        repository="repo-A",
        baseline_id="baseline-1",
        baseline_sha="0" * 40,
        change_class=ChangeClass.DOCUMENTATION_ONLY,
    )
    wf.propose(st.workflow_id, {"proposal_id": "proposal-1"})

    scope = ScopeSpec(
        repository="repo-B",
        baseline_id="baseline-1",
        operations=("edit",),
        subjects=("file.txt",),
        change_classes=(ChangeClass.DOCUMENTATION_ONLY.value,),
    )
    wf.authorize(
        st.workflow_id,
        actor="human",
        operation="edit",
        subject="file.txt",
        reason="Repository-scope regression test",
        scope=scope,
    )

    edit_called = False

    def edit_fn():
        nonlocal edit_called
        edit_called = True
        return ["file.txt"]

    with pytest.raises(ScopeViolation):
        wf.transform(
            st.workflow_id,
            current_sha="0" * 40,
            operation="edit",
            subject="file.txt",
            edit_fn=edit_fn,
        )

    assert not edit_called
    assert st.files_changed == []


def test_validate_scoped_none_change_class_raises_scope_violation():
    import pytest
    from warden.horsemen.authorization_scope import ScopeViolation, validate_scoped

    grant = make_grant()

    with pytest.raises(ScopeViolation):
        validate_scoped(
            grant,
            operation="transform",
            subject="/repo",
            baseline_id="baseline-1",
            change_class=None,
            repository="example-repo",
        )
