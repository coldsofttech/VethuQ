from __future__ import annotations

import pytest

import vethuq
from vethuq import errors
from vethuq._errors import (
    _CorruptDatabaseError,
    _DataFolderNotWritableError,
    _InvalidConfigError,
    _LanguageUnavailableError,
    _OcrModelMissingError,
    _SchemaVersionError,
    _StaleLockError,
    _StartupError,
    _VethuQError,
)

# (internal class, public counterpart, exit code)
_PAIRS = [
    (_InvalidConfigError, errors.InvalidConfigError, 10),
    (_DataFolderNotWritableError, errors.DataFolderNotWritableError, 11),
    (_CorruptDatabaseError, errors.CorruptDatabaseError, 12),
    (_OcrModelMissingError, errors.OcrModelMissingError, 13),
    (_SchemaVersionError, errors.SchemaVersionError, 14),
    (_StaleLockError, errors.StaleLockError, 15),
    (_LanguageUnavailableError, errors.LanguageUnavailableError, 16),
]


# Errors that stop VethuQ from starting; the rest are run-time errors.
_STARTUP = (
    errors.InvalidConfigError,
    errors.DataFolderNotWritableError,
    errors.SchemaVersionError,
    errors.StaleLockError,
)
_RUNTIME = (
    errors.CorruptDatabaseError,
    errors.OcrModelMissingError,
    errors.LanguageUnavailableError,
)


class TestVethuQError:
    def test_str_joins_message_and_hint(self):
        err = _VethuQError("Something broke.", "Try again.")

        assert str(err) == "Something broke. Try again."

    def test_str_is_just_the_message_without_a_hint(self):
        assert str(_VethuQError("Something broke.")) == "Something broke."

    def test_exposes_message_hint_and_exit_code(self):
        err = _VethuQError("Broke.", "Fix it.")

        assert (err.message, err.hint, err.exit_code) == ("Broke.", "Fix it.", 1)

    def test_hint_defaults_to_none(self):
        assert _VethuQError("Broke.").hint is None

    def test_args_hold_the_message(self):
        assert _VethuQError("Broke.", "Fix it.").args == ("Broke.",)

    def test_startup_error_shares_the_behaviour(self):
        err = _StartupError("Broke.", "Fix it.")

        assert isinstance(err, errors.VethuQError)
        assert (str(err), err.exit_code) == ("Broke. Fix it.", 1)


class TestInternalErrors:
    @pytest.mark.parametrize(("internal", "public", "code"), _PAIRS)
    def test_internal_error_is_caught_as_its_public_counterpart(self, internal, public, code):
        with pytest.raises(public) as excinfo:
            raise internal("Broke.", "Fix it.")

        assert type(excinfo.value) is internal
        assert excinfo.value.exit_code == code
        assert str(excinfo.value) == "Broke. Fix it."

    @pytest.mark.parametrize(("internal", "public", "code"), _PAIRS)
    def test_every_internal_error_is_caught_as_vethuq_error(self, internal, public, code):
        with pytest.raises(errors.VethuQError):
            raise internal("Broke.")

    @pytest.mark.parametrize(("internal", "public", "code"), _PAIRS)
    def test_only_startup_failures_are_caught_as_startup_error(self, internal, public, code):
        assert isinstance(internal("Broke."), errors.StartupError) == (public in _STARTUP)

    def test_siblings_do_not_catch_each_other(self):
        with pytest.raises(_StaleLockError):
            try:
                raise _StaleLockError("Stale.")
            except errors.InvalidConfigError:  # pragma: no cover - must not match
                pytest.fail("InvalidConfigError caught a StaleLockError")

    def test_every_error_has_a_distinct_non_zero_exit_code(self):
        codes = [code for _, _, code in _PAIRS]

        assert all(c != 0 for c in codes)
        assert len(set(codes)) == len(codes)
        assert [i.exit_code for i, _, _ in _PAIRS] == codes


class TestPublicErrors:
    def test_public_module_is_reachable_from_the_package(self):
        assert vethuq.errors is errors

    def test_public_classes_form_one_hierarchy(self):
        assert issubclass(errors.VethuQError, Exception)
        assert issubclass(errors.StartupError, errors.VethuQError)
        assert all(issubclass(p, errors.StartupError) for p in _STARTUP)
        assert all(
            issubclass(p, errors.VethuQError) and not issubclass(p, errors.StartupError)
            for p in _RUNTIME
        )
        assert {p for _, p, _ in _PAIRS} == {*_STARTUP, *_RUNTIME}

    def test_public_module_exposes_no_internal_names(self):
        names = [n for n in vars(errors) if not n.startswith("__")]

        assert not [n for n in names if n.startswith("_")]
        assert not any(isinstance(getattr(errors, n), type) and n.startswith("_") for n in names)
