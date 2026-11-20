"""LOCKED test 4: the live API matches contract/openapi.yaml (SPEC 1 and 3).

- Every GET operation (plus every concrete GET example in fixtures/index.json) answers
  200 for ``owner`` and its JSON validates against the documented 200 schema
  (jsonschema Draft 2020-12, ``$ref`` resolved from the OpenAPI components).
- Every operation rejects a role missing from its ``x-roles`` with 403
  ``{"detail": "forbidden for role <r>"}``.
- Owner-only actions refuse every other role and change nothing; a missing header is owner.
- An unknown job card is 404.
"""
import asyncio
import json
import re
from contextlib import suppress
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator

pytestmark = pytest.mark.integration

CONTRACT = Path(__file__).resolve().parents[2] / "contract"
FIXTURES = CONTRACT / "fixtures"
SPEC = yaml.safe_load((CONTRACT / "openapi.yaml").read_text(encoding="utf-8"))
COMPONENTS = SPEC["components"]
INDEX = json.loads((FIXTURES / "index.json").read_text(encoding="utf-8"))
ROLES = tuple(COMPONENTS["parameters"]["XRole"]["schema"]["enum"])
METHODS = ("get", "post", "put", "patch", "delete")

OPS = [
    (method.upper(), path, op)
    for path, item in SPEC["paths"].items()
    for method, op in item.items()
    if method in METHODS
]

# Path ids from the fixture story (JC-1301 for Fresh Juice, LOCKED client CL-011, ...).
ID_BY_PREFIX = {
    "/api/clients/": "CL-011",
    "/api/enquiries/": "ENQ-0045",
    "/api/dispatch/": "DC-1388",
    "/api/production/runs/": "RUN-05531",
    "/api/agents/findings/": "F-0231",
}
ID_BY_NAME = {"job_card": "JC-1301", "dispatch_id": "DC-1388"}
REQUIRED_QUERY = {
    "/api/search": "q=1301",
    "/api/production/counter/stream": "run_id=RUN-05582",  # the running press in the story
}
# Request bodies come from the POST/PUT example fixtures; these fill what they lack.
BODY_OVERRIDES = {
    ("POST", "/api/agents/run"): {"agent": "all"},
    ("POST", "/api/agents/findings/{id}/edit"): {"payload": {}},
}


def fill(path: str) -> str:
    def value(match: re.Match) -> str:
        name = match.group(1)
        if name in ID_BY_NAME:
            return ID_BY_NAME[name]
        for prefix, ident in ID_BY_PREFIX.items():
            if path.startswith(prefix):
                return ident
        raise KeyError(f"no story id for {{{name}}} in {path}")

    return re.sub(r"\{(\w+)\}", value, path)


def required_query(path: str, op: dict) -> list[str]:
    return [p["name"] for p in op.get("parameters", []) if p.get("in") == "query" and p.get("required")]


def url_for(path: str, op: dict) -> str:
    url = fill(path)
    if required_query(path, op):
        url += "?" + REQUIRED_QUERY[path]
    return url


def template_of(url_path: str) -> str:
    for path, item in SPEC["paths"].items():
        if "get" in item and re.fullmatch(re.sub(r"\\\{\w+\\\}", "[^/]+", re.escape(path)), url_path):
            return path
    raise KeyError(url_path)


def _get_cases() -> list:
    cases = {url_for(path, op): path for method, path, op in OPS if method == "GET"}
    for key in INDEX:
        method, _, url = key.partition(" ")
        if method != "GET" or "{" in url or url in cases:
            continue
        path_part, _, query = url.partition("?")
        template = template_of(path_part)
        op = SPEC["paths"][template]["get"]
        if all(f"{name}=" in query for name in required_query(template, op)):
            cases[url] = template
    return [pytest.param(url, template, id=url) for url, template in sorted(cases.items())]


def _role_cases() -> list:
    cases = []
    for method, path, op in OPS:
        denied = [r for r in ROLES if r not in op["x-roles"]]
        if denied:
            cases.append(pytest.param(method, path, denied[0], id=f"{method} {path} as {denied[0]}"))
    return cases


def assert_valid(instance, schema: dict) -> None:
    root = {**schema, "components": COMPONENTS}
    validator = Draft202012Validator(root, format_checker=Draft202012Validator.FORMAT_CHECKER)
    errors = sorted(validator.iter_errors(instance), key=lambda e: list(map(str, e.absolute_path)))
    assert not errors, "\n".join(
        f"{'/'.join(map(str, e.absolute_path)) or '<root>'}: {e.message}" for e in errors[:15]
    )


def request_kwargs(method: str, path: str, op: dict) -> dict:
    content = op.get("requestBody", {}).get("content", {})
    if "multipart/form-data" in content:
        pdf = (FIXTURES / "challan_DC-1388.pdf").read_bytes()
        return {"files": {"file": ("po.pdf", pdf, "application/pdf")}}
    if "application/json" not in content:
        return {}
    if (method, path) in BODY_OVERRIDES:
        return {"json": BODY_OVERRIDES[(method, path)]}
    name = content["application/json"]["schema"]["$ref"].rsplit("/", 1)[-1]
    props = COMPONENTS["schemas"][name].get("properties", {})
    example = json.loads((FIXTURES / INDEX[f"{method} {path}"]).read_text(encoding="utf-8"))
    return {"json": {k: v for k, v in example.items() if k in props}}


def sse_request(api, url: str, role: str = "owner", timeout: float = 20.0) -> tuple[int, dict, list]:
    """GET an SSE endpoint straight through ASGI and stop after the first event.

    TestClient waits for the whole body, which never ends for a live counter stream.
    Returns (status, headers, [data payload of each complete event]).
    """
    path, _, query = url.partition("?")
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "server": ("testserver", 80),
        "client": ("testclient", 50000),
        "root_path": "",
        "path": path,
        "raw_path": path.encode(),
        "query_string": query.encode(),
        "headers": [(b"host", b"testserver"), (b"accept", b"text/event-stream"), (b"x-role", role.encode())],
        "state": api.app_state,
    }
    result = {"status": 0, "headers": {}, "body": b""}

    async def run() -> None:
        done = asyncio.Event()
        request_sent = False

        async def receive():
            nonlocal request_sent
            if not request_sent:
                request_sent = True
                return {"type": "http.request", "body": b"", "more_body": False}
            await done.wait()
            return {"type": "http.disconnect"}

        async def send(message):
            if message["type"] == "http.response.start":
                result["status"] = message["status"]
                result["headers"] = {k.decode().lower(): v.decode() for k, v in message.get("headers", [])}
            elif message["type"] == "http.response.body":
                result["body"] += message.get("body", b"")
                complete_event = re.search(rb"^data:.*?\r?\n\r?\n", result["body"], re.M | re.S)
                if complete_event or not message.get("more_body", False):
                    done.set()

        task = asyncio.ensure_future(api.app(scope, receive, send))
        waiter = asyncio.ensure_future(done.wait())
        await asyncio.wait({task, waiter}, timeout=timeout, return_when=asyncio.FIRST_COMPLETED)
        done.set()
        waiter.cancel()
        if task.done():
            task.result()  # surface app errors
        else:
            task.cancel()
            with suppress(BaseException):
                await task

    asyncio.run(run())
    text = result["body"].decode("utf-8", errors="replace").replace("\r\n", "\n")
    events = []
    for block in text.split("\n\n")[:-1]:
        data = [line[5:].lstrip() for line in block.split("\n") if line.startswith("data:")]
        if data:
            events.append("\n".join(data))
    return result["status"], result["headers"], events


# ---- every GET returns the documented shape -------------------------------------------------

@pytest.mark.parametrize("url, template", _get_cases())
def test_get_matches_openapi_schema(api, url, template):
    ok = SPEC["paths"][template]["get"]["responses"]["200"]["content"]
    content_type = next(iter(ok))
    if content_type == "text/event-stream":
        status, headers, events = sse_request(api, url)
        assert status == 200
        assert headers.get("content-type", "").startswith("text/event-stream")
        assert events, "stream sent no complete `data:` event"
        assert_valid(json.loads(events[0]), {"$ref": "#/components/schemas/CounterTick"})
    elif content_type == "application/pdf":
        r = api.get(url)
        assert r.status_code == 200, r.text
        assert r.headers["content-type"].startswith("application/pdf")
        assert r.content.startswith(b"%PDF")
    else:
        r = api.get(url)
        assert r.status_code == 200, r.text
        assert_valid(r.json(), ok["application/json"]["schema"])


# ---- roles ---------------------------------------------------------------------------------------

@pytest.mark.parametrize("method, path, role", _role_cases())
def test_role_not_in_x_roles_gets_403(api, method, path, role):
    op = SPEC["paths"][path][method.lower()]
    assert "owner" in op["x-roles"], "owner may call everything"
    url = url_for(path, op)
    if "text/event-stream" in op["responses"].get("200", {}).get("content", {}):
        status, _, _ = sse_request(api, url, role=role)
        assert status == 403
        return
    r = api.request(method, url, role=role, **request_kwargs(method, path, op))
    assert r.status_code == 403, f"{method} {url} as {role}: {r.status_code} {r.text}"
    assert r.json() == {"detail": f"forbidden for role {role}"}


@pytest.mark.parametrize("role", [r for r in ROLES if r != "owner"])
def test_owner_only_actions_refuse_other_roles(api, role):
    r = api.put("/api/settings", role=role, json={"grace_days": 30})
    assert r.status_code == 403, r.text
    assert r.json() == {"detail": f"forbidden for role {role}"}

    r = api.post("/api/clients/CL-011/release-lock", role=role, json={"reason": "paid by phone"})
    assert r.status_code == 403, r.text
    assert r.json() == {"detail": f"forbidden for role {role}"}

    assert api.get("/api/settings").json()["grace_days"] == 15
    assert api.get("/api/clients/CL-011").json()["client"]["lock_status"] == "locked"


def test_missing_role_header_means_owner(api):
    # owner/accounts-only endpoint
    r = api.get("/api/dashboard/summary?period=month", role=None)
    assert r.status_code == 200, r.text
    assert api.get("/api/dashboard/summary?period=month", role="store").status_code == 403


# ---- not found -----------------------------------------------------------------------------------

@pytest.mark.parametrize(
    "path", [path for method, path, op in OPS if method == "GET" and "{job_card}" in path]
)
def test_unknown_job_card_is_404(api, path):
    r = api.get(path.replace("{job_card}", "JC-9999"))
    assert r.status_code == 404, r.text
    assert isinstance(r.json().get("detail"), str)
