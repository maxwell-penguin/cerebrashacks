import asyncio

from cerebras.cloud.sdk._exceptions import APITimeoutError

import vision_client
from cerebras_client import CerebrasClient


def test_cerebras_vision_retries_transient_timeout(monkeypatch):
    monkeypatch.setenv("CEREBRAS_API_KEY", "test")
    monkeypatch.setenv("VISION_PROVIDER", "cerebras")
    calls = []

    async def flaky(self, messages, *, max_tokens, temperature):
        calls.append(1)
        if len(calls) == 1:
            raise APITimeoutError(request=None)
        return '{"ok": true}'

    monkeypatch.setattr(CerebrasClient, "_acall_once", flaky)
    out = vision_client.call_vision_json("sys", "user", b"\x89PNG", "image/png")
    assert out == '{"ok": true}'
    assert len(calls) == 2
