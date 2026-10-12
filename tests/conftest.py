# SPDX-FileCopyrightText: Copyright (c) 2024 MLCommons
# SPDX-License-Identifier: Apache-2.0
"""Suite-wide fixtures."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from endpoints_submission_cli import _version_check
from submission_checker import messages


@pytest.fixture(autouse=True)
def _strict_messages() -> Iterator[None]:
    """A check result whose message cannot render fails the test that produced it.

    Outside tests the catalog degrades to a generic message instead, so a wording
    mistake never stops a submission from being checked.
    """
    previous = messages.strict
    messages.strict = True
    try:
        yield
    finally:
        messages.strict = previous


@pytest.fixture(autouse=True)
def _no_pypi(monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory) -> None:
    """Keep the version check off PyPI and out of ~/.cache: no newer release is known.

    Tests of the check patch ``_fetch_latest`` and ``_current_version`` themselves.
    """
    cache = tmp_path_factory.mktemp("version-check") / "version_check.json"
    monkeypatch.setattr(_version_check, "_CACHE_PATH", cache)
    monkeypatch.setattr(_version_check, "_fetch_latest", lambda: None)
