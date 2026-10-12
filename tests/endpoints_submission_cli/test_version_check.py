# SPDX-FileCopyrightText: Copyright (c) 2024 MLCommons
# SPDX-License-Identifier: Apache-2.0
"""Tests for the PyPI version check and the upgrade notice."""

from __future__ import annotations

import json
import time
from collections.abc import Callable

import pytest

from endpoints_submission_cli import _version_check


def _installed(monkeypatch: pytest.MonkeyPatch, version: str) -> None:
    monkeypatch.setattr(_version_check, "_current_version", lambda: version)


def _pypi(monkeypatch: pytest.MonkeyPatch, version: str | None) -> list[int]:
    """PyPI reports *version* as the latest release; returns a call counter."""
    calls = [0]

    def fetch() -> str | None:
        calls[0] += 1
        return version

    monkeypatch.setattr(_version_check, "_fetch_latest", fetch)
    return calls


def _cache(version: str, age: float = 0.0) -> None:
    _version_check._CACHE_PATH.write_text(json.dumps({"latest": version, "ts": time.time() - age}))


@pytest.mark.unit
class TestIsNewer:
    @pytest.mark.parametrize(
        ("latest", "current"),
        [
            ("1.4.0.0", "1.3.2.0"),
            ("1.4.0.1", "1.4.0.0"),  # the fourth part counts
            ("1.4.0.1", "1.4.0"),
            ("1.4.0.0", "unknown"),
        ],
    )
    def test_newer(self, latest: str, current: str) -> None:
        assert _version_check._is_newer(latest, current)

    @pytest.mark.parametrize(
        ("latest", "current"),
        [
            ("1.4.0.0", "1.4.0.0"),
            ("1.4.0.0", "1.4.0"),
            ("1.4.0.0", "1.4.1.dev3+g12ab"),  # a dev build is ahead of its base release
            ("1.4.0.0", "1.5.0.0"),
        ],
    )
    def test_not_newer(self, latest: str, current: str) -> None:
        assert not _version_check._is_newer(latest, current)

    @pytest.mark.parametrize(
        ("latest", "current", "newer"),
        [
            ("1.4.1.0", "1.4.0.0", False),
            ("1.4.1.0", "1.4", False),
            ("1.5.0.0", "1.4.9.9", True),
            ("2.0.0.0", "1.9.0.0", True),
        ],
    )
    def test_major_minor_only(self, latest: str, current: str, newer: bool) -> None:
        assert _version_check._is_newer(latest, current, components=2) is newer


@pytest.mark.unit
class TestOutdated:
    def test_patch_behind_is_outdated_but_not_rejected(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _installed(monkeypatch, "1.4.0.0")
        _pypi(monkeypatch, "1.4.1.0")
        assert _version_check.outdated() == ("1.4.0.0", "1.4.1.0")
        assert _version_check.outdated(components=_version_check.REQUIRED_COMPONENTS) is None

    def test_minor_behind_is_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _installed(monkeypatch, "1.3.2.0")
        _pypi(monkeypatch, "1.4.1.0")
        assert _version_check.outdated(components=2) == ("1.3.2.0", "1.4.1.0")

    def test_older_install_is_outdated(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _installed(monkeypatch, "1.3.2.0")
        _pypi(monkeypatch, "1.4.0.0")
        assert _version_check.outdated() == ("1.3.2.0", "1.4.0.0")

    def test_latest_install_is_not(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _installed(monkeypatch, "1.4.0.0")
        _pypi(monkeypatch, "1.4.0.0")
        assert _version_check.outdated() is None

    def test_unknown_when_pypi_and_cache_are_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _installed(monkeypatch, "1.3.2.0")
        _pypi(monkeypatch, None)
        assert _version_check.outdated() is None

    def test_uses_the_cache(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _installed(monkeypatch, "1.3.2.0")
        calls = _pypi(monkeypatch, "1.5.0.0")
        _cache("1.4.0.0")
        assert _version_check.outdated() == ("1.3.2.0", "1.4.0.0")
        assert calls[0] == 0

    def test_fresh_skips_the_cache(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _installed(monkeypatch, "1.4.0.0")
        _pypi(monkeypatch, "1.5.0.0")
        _cache("1.4.0.0")
        assert _version_check.outdated(fresh=True) == ("1.4.0.0", "1.5.0.0")

    def test_fresh_falls_back_to_the_cache(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _installed(monkeypatch, "1.3.2.0")
        _pypi(monkeypatch, None)
        _cache("1.4.0.0")
        assert _version_check.outdated(fresh=True) == ("1.3.2.0", "1.4.0.0")

    def test_expired_cache_is_refetched(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _installed(monkeypatch, "1.3.2.0")
        calls = _pypi(monkeypatch, "1.4.0.0")
        _cache("1.3.2.0", age=_version_check._CACHE_TTL + 1)
        assert _version_check.outdated() == ("1.3.2.0", "1.4.0.0")
        assert calls[0] == 1


@pytest.mark.unit
class TestUpgradeNotice:
    @pytest.fixture
    def at_exit(self, monkeypatch: pytest.MonkeyPatch) -> list[Callable[[], None]]:
        """Capture the exit handler instead of registering it with the interpreter."""
        handlers: list[Callable[[], None]] = []
        monkeypatch.setattr(_version_check, "_registered", False)
        monkeypatch.setattr(_version_check.atexit, "register", handlers.append)
        return handlers

    def _notice(self, handlers: list[Callable[[], None]], capsys: pytest.CaptureFixture) -> str:
        _version_check.register_upgrade_notice()
        for handler in handlers:
            handler()
        return " ".join(capsys.readouterr().err.split())

    def test_older_install_is_told_to_upgrade(
        self, monkeypatch: pytest.MonkeyPatch, at_exit, capsys
    ) -> None:
        _installed(monkeypatch, "1.3.2.0")
        _pypi(monkeypatch, "1.4.0.0")
        err = self._notice(at_exit, capsys)
        assert "A new version of endpoints-submission-cli is available: 1.3.2.0 → 1.4.0.0" in err
        assert "pip install --upgrade endpoints-submission-cli" in err

    def test_older_install_is_told_from_the_cache(
        self, monkeypatch: pytest.MonkeyPatch, at_exit, capsys
    ) -> None:
        _installed(monkeypatch, "1.3.2.0")
        calls = _pypi(monkeypatch, None)
        _cache("1.4.0.0")
        assert "1.3.2.0 → 1.4.0.0" in self._notice(at_exit, capsys)
        assert calls[0] == 0

    def test_latest_install_is_not(self, monkeypatch: pytest.MonkeyPatch, at_exit, capsys) -> None:
        _installed(monkeypatch, "1.4.0.0")
        _pypi(monkeypatch, "1.4.0.0")
        assert self._notice(at_exit, capsys) == ""

    def test_nothing_when_pypi_is_unreachable(
        self, monkeypatch: pytest.MonkeyPatch, at_exit, capsys
    ) -> None:
        _installed(monkeypatch, "1.3.2.0")
        _pypi(monkeypatch, None)
        assert self._notice(at_exit, capsys) == ""
