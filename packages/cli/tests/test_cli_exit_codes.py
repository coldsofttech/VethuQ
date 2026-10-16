from __future__ import annotations

import inspect
from types import SimpleNamespace

import pytest
import typer
from vethuq_cli import commands as commands_module
from vethuq_cli import exit_codes

import vethuq.errors as errors
from vethuq.enums import IndexRunStatus, UpdateStatus


def test_each_error_has_its_own_documented_range():
    codes = {
        c.exit_code
        for _, c in inspect.getmembers(errors, inspect.isclass)
        if issubclass(c, errors.VethuQError) and c.exit_code != 1
    }
    assert exit_codes.CREDITS_EMPTY == errors.CreditsExhaustedError.exit_code
    assert exit_codes.LICENCE_NOT_OK == errors.LicenceError.exit_code
    assert not codes & {exit_codes.WAITING_CREDITS, exit_codes.WAITING_REMOTE}


@pytest.mark.parametrize(
    ("status", "code"),
    [
        (IndexRunStatus.WAITING_CREDITS, exit_codes.WAITING_CREDITS),
        (IndexRunStatus.WAITING_REMOTE, exit_codes.WAITING_REMOTE),
    ],
)
def test_a_run_that_stopped_early_says_so(monkeypatch, status, code):
    monkeypatch.setattr(commands_module, "facts", lambda *a, **k: None)
    with pytest.raises(typer.Exit) as stopped:
        commands_module._run_report(SimpleNamespace(id=1, status=status))
    assert stopped.value.exit_code == code


def test_a_finished_run_exits_normally(monkeypatch):
    monkeypatch.setattr(commands_module, "facts", lambda *a, **k: None)
    commands_module._run_report(SimpleNamespace(id=1, status=IndexRunStatus.COMPLETED))


@pytest.mark.parametrize(
    ("status", "flag", "code"),
    [
        (UpdateStatus.AVAILABLE, True, exit_codes.UPDATE_AVAILABLE),
        (UpdateStatus.BELOW_MINIMUM, True, exit_codes.BELOW_MINIMUM),
    ],
)
def test_update_codes_only_with_the_flag(status, flag, code):
    with pytest.raises(typer.Exit) as stopped:
        commands_module._update_exit(SimpleNamespace(status=status), flag)
    assert stopped.value.exit_code == code
    commands_module._update_exit(SimpleNamespace(status=status), False)
