"""``hermes update`` tells the user about a pre-PM ``uv``/``uvx`` — on every platform.

The notice is the only surface that reaches a user who is not already running
``doctor``, so its two contracts are that it appears at all, and that the command
it prints actually names the home the file is in. Both are asserted by running the
notice and reading what a user would read.

The platform split matters (#101269): POSIX can be repaired automatically, Windows
cannot, and :func:`legacy_uv.automatic_cleanup` is POSIX-only. That must decide the
WANTED REMEDY, never whether the user hears about the shadow at all — a silent
Windows update is how the residue stayed undiscoverable in the first place.
"""
from __future__ import annotations

import shlex

import pytest

from hermes_cli import legacy_uv
from hermes_cli.update_cmd_maint import _notice_legacy_managed_uv
from tests.hermes_cli.legacy_uv_support import _pre_pm_binary

pytest_plugins = ["tests.hermes_cli.legacy_uv_support"]


@pytest.fixture
def store_has_uv(monkeypatch):
    """PM's store already carries a uv, so the legacy copy is removable."""
    import pm

    monkeypatch.setattr(pm, "is_installed", lambda name: True)


def test_the_notice_stays_silent_while_the_legacy_copy_is_the_only_uv(home, monkeypatch, capsys, store_has_uv):
    """Naming a file as removable while it is the install's only uv invites a broken tree."""
    import pm

    monkeypatch.setattr(pm, "is_installed", lambda name: False)
    _pre_pm_binary(home / "bin" / "uv")

    _notice_legacy_managed_uv()

    assert "shadow your own uv" not in capsys.readouterr().out


@pytest.mark.platforms("posix")
def test_the_notice_names_a_command_that_targets_the_reported_home(home, capsys, store_has_uv):
    """On a platform that can fix it, the printed command must be runnable and scoped."""
    _pre_pm_binary(home / "bin" / "uv")

    _notice_legacy_managed_uv()

    out = capsys.readouterr().out
    assert "shadow your own uv" in out, "the leftover must be reported"
    assert "doctor --fix" in out, "an automatic platform must offer the automatic repair"
    # The advice is scoped to THIS home: doctor resolves one HERMES_HOME, so an
    # unscoped ``hermes doctor --fix`` would leave a leftover found elsewhere.
    scoped = f"HERMES_HOME={shlex.quote(str(home))}"
    assert scoped in out, (
        f"the printed command does not name the home the file is in ({scoped}): {out}"
    )


@pytest.mark.platforms("posix")
def test_the_notice_says_so_when_the_platform_cannot_fix_it(home, monkeypatch, capsys, store_has_uv):
    """A fail-closed platform must still be told, and told the manual step.

    ``automatic_cleanup()`` is False on Windows (no directory-relative deletion),
    so the remedy there is manual. Silence is not the remedy: it is the reason the
    shadow went unnoticed. Simulated by forcing the capability verdict, which is
    the same switch the real call site reads.
    """
    monkeypatch.setattr(legacy_uv, "automatic_cleanup", lambda: False)
    _pre_pm_binary(home / "bin" / "uv")

    _notice_legacy_managed_uv()

    out = capsys.readouterr().out
    assert "shadow your own uv" in out, "a platform that cannot auto-fix must still report"
    assert "not performed on this platform" in out, (
        f"the notice must not imply a --fix that can only repeat itself: {out}"
    )
    assert "by hand" in out, "the manual remedy must be stated"
    assert "doctor --fix" not in out, "no automatic repair exists here to offer"


@pytest.mark.platforms("posix")
def test_the_notice_is_quiet_when_there_is_nothing_to_report(home, capsys, store_has_uv):
    (home / "bin" / "hermes").write_text("#!/usr/bin/env sh\n", encoding="utf-8")

    _notice_legacy_managed_uv()

    assert "shadow your own uv" not in capsys.readouterr().out


def test_the_notice_never_fails_the_update_tail(home, monkeypatch, capsys):
    """A notice is best-effort: a damaged install must not turn an update into a failure."""
    import pm

    def boom(name):
        raise ValueError("pm/lock.json is corrupt")

    monkeypatch.setattr(pm, "is_installed", boom)
    _pre_pm_binary(home / "bin" / "uv")

    _notice_legacy_managed_uv()  # must not raise

    assert "shadow your own uv" not in capsys.readouterr().out
