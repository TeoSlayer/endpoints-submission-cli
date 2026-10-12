# SPDX-FileCopyrightText: Copyright (c) 2024 MLCommons
# SPDX-License-Identifier: Apache-2.0
"""Unit tests for _http transport module (token resolution and HTTP helpers)."""

from __future__ import annotations

import httpx
import pytest

from endpoints_submission_cli._http import _base_url, _raise_status, get_token
from endpoints_submission_cli.exceptions import APIError, AuthError


@pytest.mark.unit
class TestGetToken:
    def test_explicit_token_returned(self) -> None:
        assert get_token("mlc_abc") == "mlc_abc"

    def test_env_var_used_when_no_explicit(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PRISM_USER_API_TOKEN", "mlc_env")
        assert get_token(None) == "mlc_env"

    def test_explicit_takes_precedence_over_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PRISM_USER_API_TOKEN", "mlc_env")
        assert get_token("mlc_explicit") == "mlc_explicit"

    def test_no_token_raises_auth_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("PRISM_USER_API_TOKEN", raising=False)
        with pytest.raises(AuthError):
            get_token(None)


@pytest.mark.unit
class TestBaseUrl:
    def test_default_is_the_custom_domain(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Not the generated *.run.app URL, which changes if the service is recreated."""
        monkeypatch.delenv("MLPERF_API_BASE_URL", raising=False)
        assert _base_url() == "https://endpointsapi.mlcommons.org"

    def test_env_var_overrides_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MLPERF_API_BASE_URL", "http://localhost:8080")
        assert _base_url() == "http://localhost:8080"


def _status_error(code: int, **response: object) -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "https://api.test/submissions")
    return httpx.HTTPStatusError(
        "error", request=request, response=httpx.Response(code, request=request, **response)
    )


@pytest.mark.unit
class TestRaiseStatus:
    def test_upgrade_required_shows_only_the_detail(self) -> None:
        detail = (
            "Creating a submission requires endpoints-submission-cli 1.4.0.0 or later."
            " Upgrade with: pip install --upgrade endpoints-submission-cli"
        )
        with pytest.raises(APIError) as info:
            _raise_status(_status_error(426, json={"detail": detail}))
        assert str(info.value) == detail

    def test_upgrade_required_without_json_keeps_the_body(self) -> None:
        with pytest.raises(APIError, match="upgrade please"):
            _raise_status(_status_error(426, text="upgrade please"))

    def test_other_errors_keep_the_status_and_body(self) -> None:
        with pytest.raises(APIError, match=r"API error 400: .*bad run"):
            _raise_status(_status_error(400, json={"detail": "bad run"}))
