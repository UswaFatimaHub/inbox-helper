from unittest.mock import patch

import pytest

from inbox_helper.providers import Completion, GeminiClient, ProviderError


def test_gemini_steps_down_models_when_busy():
    client = GeminiClient("key", ("newest", "older", "oldest"), 10)
    calls = []

    def fake(model, system, user):
        calls.append(model)
        if model == "newest":
            raise ProviderError("HTTP 503: busy", status=503)
        return Completion("{}", model, 0.1)

    with patch.object(client, "_complete", side_effect=fake):
        assert client.complete("s", "u").model == "older"
    assert calls == ["newest", "older"]


def test_gemini_does_not_step_down_on_auth_error():
    client = GeminiClient("key", ("a", "b"), 10)
    with patch.object(client, "_complete", side_effect=ProviderError("HTTP 401", disable_lane=True, status=401)):
        with pytest.raises(ProviderError):
            client.complete("s", "u")
        assert client._complete.call_count == 1
