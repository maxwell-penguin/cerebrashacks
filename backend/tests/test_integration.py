"""Integration tests: real orchestrator + real CerebrasClient retry logic, fake transport.

Call numbering (one counter shared by every model call): 1 vision_parser, 2 architect,
3 code_forge, 4 auditor, 5 accessibility, 6 vision_critic. Each retry attempt counts as a call.
No network and no real API key are needed, so these never skip.
"""

import json

import httpx
import pytest
from cerebras.cloud.sdk._exceptions import APIConnectionError, APITimeoutError, RateLimitError

import cerebras_client
import orchestrator
from agent_prompts import AUDITOR_SYSTEM, VISION_CRITIC_SYSTEM
from cerebras_client import CerebrasClient

REQ = httpx.Request("POST", "http://fake")
CODE = "export default function App() {\n  return <main>hi</main>;\n}"

JSON_BY_AGENT = {
    "vision": {"screen_title": "T", "components": [{"type": "button", "label": "Go"}]},
    "architect": {"component_tree": "App\n- Button", "layout_plan": "stack"},
    "auditor": {"issues": [], "summary": "ok"},
    "critic": {"passed": True, "status": "pass", "issues": [], "summary": "ok"},
}


def _make_error(error_type):
    if error_type == "timeout":
        return APITimeoutError(request=REQ)
    if error_type == "api":
        return APIConnectionError(request=REQ)
    if error_type == "rate_limit":
        return RateLimitError("slow down", response=httpx.Response(429, request=REQ), body=None)
    raise ValueError(error_type)


class FakeCerebrasClient(CerebrasClient):
    """Fakes only the transport (_acall_once / _iter_stream_tokens), so the real
    retry + rate-limit wrappers in acall / acall_stream run. Calls fail_at_call ..
    fail_at_call + fail_count - 1 raise; fail_count=2 exhausts the single retry."""

    def __init__(self, fail_at_call=None, error_type="timeout", fail_count=2):
        super().__init__(api_key="fake", model="fake")
        self.fail_at_call, self.error_type, self.fail_count = fail_at_call, error_type, fail_count
        self.calls = 0
        self.log: list[str] = []

    def _tick(self, name):
        self.calls += 1
        self.log.append(name)
        if self.fail_at_call is not None and self.fail_at_call <= self.calls < self.fail_at_call + self.fail_count:
            raise _make_error(self.error_type)

    async def _acall_once(self, messages, *, max_tokens, temperature):
        # architect and auditor are the only JSON text calls
        name = "auditor" if messages[0]["content"] == AUDITOR_SYSTEM else "architect"
        self._tick(name)
        return json.dumps(JSON_BY_AGENT[name])

    async def _iter_stream_tokens(self, messages, *, max_tokens, temperature):
        self._tick("stream")
        for tok in (CODE[:20], CODE[20:]):
            yield tok

    def vision_call(self, *_args):
        self._tick("vision")
        return json.dumps(JSON_BY_AGENT["critic" if _args[0] == VISION_CRITIC_SYSTEM else "vision"])


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("ARCHITECT_PROVIDER", "client")  # use the injected client for the architect
    monkeypatch.setattr(cerebras_client, "RATE_LIMIT_RETRY_DELAY", 0)


async def run(fake, monkeypatch, *, image=True, a11y=True, screenshot=True):
    monkeypatch.setattr(orchestrator, "call_vision_json", fake.vision_call)
    events = []

    async def emit(msg):
        events.append(msg)

    result = await orchestrator.run_sketchstorm_pipeline(
        fake,
        b"img" if image else None,
        "a button",
        "image/png",
        emit,
        run_audit=True,
        run_accessibility_pass=a11y,
        screenshot_bytes=b"shot" if screenshot else None,
    )
    complete = [e for e in events if e["type"] == "pipeline_complete"]
    assert len(complete) == 1
    return result, events, complete[0]


def errored(events):
    return [e["agent"] for e in events if e["type"] == "error"]


async def test_happy_path_all_six_agents(monkeypatch):
    fake = FakeCerebrasClient()
    result, events, complete = await run(fake, monkeypatch)
    assert fake.calls == 6 and not errored(events)
    done = {e["agent"] for e in events if e["type"] == "agent_status" and e["status"] == "done"}
    assert done == {"vision_parser", "architect", "code_forge", "auditor", "accessibility", "vision_critic"}
    assert complete["success"] and "export default function App" in result["code"]


@pytest.mark.parametrize("call,agent", [(1, "vision_parser"), (2, "architect")])
@pytest.mark.parametrize("error_type", ["timeout", "api", "rate_limit"])
async def test_blocking_failure_stops_pipeline(monkeypatch, call, agent, error_type):
    # Blocking failures don't raise out of the pipeline: they emit error + pipeline_complete(success=False).
    fake = FakeCerebrasClient(fail_at_call=call, error_type=error_type, fail_count=3)  # 3 exhausts rate-limit retries
    result, events, complete = await run(fake, monkeypatch)
    assert result == {} and not complete["success"]
    assert errored(events) == [agent]
    assert "stream" not in fake.log  # code_forge and everything after never ran


@pytest.mark.parametrize("call,agent", [(5, "accessibility"), (6, "vision_critic")])
async def test_optional_failure_keeps_earlier_outputs(monkeypatch, call, agent):
    fake = FakeCerebrasClient(fail_at_call=call)
    result, events, complete = await run(fake, monkeypatch)
    assert errored(events) == [agent] and complete["success"]
    assert "export default function App" in result["code"]
    assert result["vision"] and result["architecture"] and result["audit"] is not None
    assert (result["accessibility_code"] is None) == (agent == "accessibility")
    assert (result["visual_check"] is None) == (agent == "vision_critic")


async def test_transient_failure_resolves_on_retry(monkeypatch):
    # Text-only run so call 1 is the architect, which goes through the real retry wrapper.
    fake = FakeCerebrasClient(fail_at_call=1, fail_count=1)
    result, events, complete = await run(fake, monkeypatch, image=False, screenshot=False)
    assert not errored(events) and complete["success"]
    assert fake.log[:2] == ["architect", "architect"]
    assert "export default function App" in result["code"]
