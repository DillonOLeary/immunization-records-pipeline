"""CLI entrypoint tests: parsing and dispatch. The CLI is status-only;
everything that changes state runs as the Cloud Run Job."""

import pytest

import mn_immunization.runtime.cli as cli


def test_command_is_required():
    with pytest.raises(SystemExit):
        cli.create_parser().parse_args([])


def test_status_requires_bucket():
    with pytest.raises(SystemExit):
        cli.create_parser().parse_args(["status"])


def test_dispatches_status_with_bucket_and_limit(monkeypatch):
    calls = []
    monkeypatch.setitem(
        cli.COMMANDS, "status", lambda args: calls.append((args.bucket, args.limit))
    )
    assert cli.main(["status", "--bucket", "test-bucket", "--limit", "3"]) == 0
    assert calls == [("test-bucket", 3)]
