"""LOCKED test 8 (v0.2, SPEC 6): one company can never see or change another company's data.

The parts switch on as the features land, so `dev` stays green in between. A part runs as soon
as the thing it tests exists; it is never switched off again:

- Part A, contract rules: always runs.
- Part B, database layer: runs once F1 #51 adds the `companies` table to `core.models`.
- Part C, API isolation and tokens: runs once the auth operations lose `x-status: planned` in
  `contract/openapi.yaml` (the `[contract]` PR right after B1 #53).
- Part D, platform and company admin: runs once the platform/company operations lose
  `x-status: planned` (the `[contract]` PR right after B2 #54).

Demo logins come from the contract story (contract/README.md, PR #67): every company has an
owner who signs in with the demo OTP 123456 while `AUTH_MODE=demo`.
"""
import json
import re
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
METHODS = ("get", "post", "put", "patch", "delete")
OPS = {
    f"{method.upper()} {path}": op
    for path, item in SPEC["paths"].items()
    for method, op in item.items()
    if method in METHODS
}

DEMO_OTP = "123456"
COMPANIES = ("CO-001", "CO-002", "CO-003")
OWNER_LOGINS = {  # company id -> (company_slug, owner login)
    "CO-001": ("prolabels", "+91 90000 00001"),
    "CO-002": ("sunriseflexo", "+91 90000 00201"),
    "CO-003": ("nilgirilabels", "+91 90000 00301"),
}
PLATFORM_LOGIN = ("", "admin@platform.example")

AUTH_OPS = ("POST /api/auth/otp", "POST /api/auth/login", "POST /api/auth/logout", "GET /api/auth/me")
PLATFORM_OPS = (
    "GET /api/platform/companies",
    "POST /api/platform/companies",
    "POST /api/platform/companies/{id}/import",
    "GET /api/platform/usage",
)
COMPANY_ADMIN_OPS = (
    "GET /api/company/profile",
    "GET /api/company/users",
    "POST /api/company/users",
    "PUT /api/company/users/{id}",
    "GET /api/company/connections",
)
# Tables that are not owned by one company (SPEC 6.1, schema.md).
PLATFORM_TABLES = {"companies"}
NULLABLE_COMPANY_TABLES = {"users", "sessions", "otp_codes"}  # null only for platform staff


def built(key: str) -> bool:
    """An operation exists in the contract and is no longer marked planned."""
    return key in OPS and OPS[key].get("x-status") != "planned"


def stage(ready: bool, name: str) -> list:
    """One parametrised case once the feature exists, none before (see module docstring)."""
    return [pytest.param(name, id=name)] if ready else []


def _models_have_companies() -> bool:
    try:
        from core.models import Base
    except Exception:  # pragma: no cover - core always imports in CI
        return False
    return "companies" in Base.metadata.tables


DB_STAGE = stage(_models_have_companies(), "f1-db")
API_STAGE = stage(all(built(k) for k in AUTH_OPS), "b1-auth")
PLATFORM_STAGE = stage(all(built(k) for k in AUTH_OPS + PLATFORM_OPS + COMPANY_ADMIN_OPS), "b2-platform")


def assert_valid(instance, schema: dict) -> None:
    root = {**schema, "components": COMPONENTS}
    validator = Draft202012Validator(root, format_checker=Draft202012Validator.FORMAT_CHECKER)
    errors = sorted(validator.iter_errors(instance), key=lambda e: list(map(str, e.absolute_path)))
    assert not errors, "\n".join(
        f"{'/'.join(map(str, e.absolute_path)) or '<root>'}: {e.message}" for e in errors[:15]
    )


def _schema_props(schema: dict) -> set:
    if "$ref" in schema:
        schema = COMPONENTS["schemas"][schema["$ref"].rsplit("/", 1)[-1]]
    return set(schema.get("properties", {}))


# ---- Part A: contract rules (always) --------------------------------------------------------------

@pytest.mark.parametrize("key", sorted(OPS))
def test_company_never_comes_from_the_request(key):
    """SPEC 6.2: the company comes only from the token, never from URL, query or body."""
    op = OPS[key]
    path = key.split(" ", 1)[1]
    for param in op.get("parameters", []):
        if "$ref" in param:
            continue
        assert "company" not in param["name"].lower(), f"{key}: parameter {param['name']!r}"
    assert "{company" not in path, key
    body = op.get("requestBody", {}).get("content", {}).get("application/json", {}).get("schema")
    if body:
        assert "company_id" not in _schema_props(body), f"{key}: request body has company_id"


@pytest.mark.parametrize("key", PLATFORM_OPS)
def test_platform_operations_are_platform_admin_only(key):
    assert OPS[key]["x-roles"] == ["platform_admin"], key


@pytest.mark.parametrize("key", COMPANY_ADMIN_OPS)
def test_company_admin_operations_are_owner_only(key):
    assert OPS[key]["x-roles"] == ["owner"], key


@pytest.mark.parametrize("key", AUTH_OPS + PLATFORM_OPS + COMPANY_ADMIN_OPS)
def test_v02_fixture_matches_schema(key):
    """Mock mode and the frontend use these fixtures; they must match the contract exactly."""
    op = OPS[key]
    assert key in INDEX, f"no fixture for {key} in fixtures/index.json"
    data = json.loads((FIXTURES / INDEX[key]).read_text(encoding="utf-8"))
    code = "201" if "201" in op["responses"] else "200"
    assert_valid(data, op["responses"][code]["content"]["application/json"]["schema"])


def test_v02_fixture_story_is_consistent():
    """Companies list, usage and users screens tell the same story (no screen disagrees)."""
    companies = json.loads((FIXTURES / "platform_companies.json").read_text(encoding="utf-8"))
    usage = json.loads((FIXTURES / "platform_usage.json").read_text(encoding="utf-8"))
    users = json.loads((FIXTURES / "company_users.json").read_text(encoding="utf-8"))
    profile = json.loads((FIXTURES / "company_profile.json").read_text(encoding="utf-8"))

    by_id = {c["id"]: c for c in companies["items"]}
    assert set(COMPANIES) <= set(by_id)
    assert all(c["isolation"] is True for c in companies["items"])
    for row in usage["companies"]:
        assert row["total_cost"] == by_id[row["company_id"]]["cost_month"], row["company_id"]
        assert round(row["shared_cost"] + row["direct_cost"], 2) == row["total_cost"], row["company_id"]
    assert round(sum(r["total_cost"] for r in usage["companies"]), 2) == usage["total_cost"]
    assert round(sum(c["monthly"] for c in usage["cost_lines"]), 2) == usage["total_cost"]
    assert companies["totals"]["cost_month"] == usage["total_cost"]

    active = sum(u["status"] == "active" for u in users["items"])
    assert users["totals"]["active"] == active == profile["users"] == by_id["CO-001"]["users"]


# ---- Part B: database layer (after F1) ------------------------------------------------------------

@pytest.mark.parametrize("ready", DB_STAGE)
def test_every_business_table_has_company_id(ready, tmp_path):
    from sqlalchemy import create_engine, inspect, text

    from core.etl.build import build_database

    url = f"sqlite:///{(tmp_path / 'tenants.db').as_posix()}"
    build_database(url)  # synthetic: CO-001 story + two made-up companies
    engine = create_engine(url)
    insp = inspect(engine)
    with engine.connect() as con:
        for table in insp.get_table_names():
            if table in PLATFORM_TABLES:
                continue
            cols = {c["name"]: c for c in insp.get_columns(table)}
            assert "company_id" in cols, f"{table} has no company_id"
            if table not in NULLABLE_COMPANY_TABLES:
                assert not cols["company_id"]["nullable"], f"{table}.company_id must be NOT NULL"
                nulls = con.execute(text(f'SELECT COUNT(*) FROM "{table}" WHERE company_id IS NULL')).scalar()
                assert nulls == 0, f"{table}: {nulls} rows without a company"

        ids = {r[0] for r in con.execute(text("SELECT id FROM companies"))}
        assert set(COMPANIES) <= ids
        for co in COMPANIES:
            for table in ("clients", "items", "machines", "jobs", "invoices"):
                n = con.execute(text(f'SELECT COUNT(*) FROM "{table}" WHERE company_id = :c'), {"c": co}).scalar()
                assert n > 0, f"{co} has no {table}"
            n = con.execute(text("SELECT COUNT(*) FROM settings WHERE company_id = :c"), {"c": co}).scalar()
            assert n == 1, f"{co} must have exactly one settings row, has {n}"

        names = {
            co: {r[0] for r in con.execute(text("SELECT name FROM clients WHERE company_id = :c"), {"c": co})}
            for co in COMPANIES
        }
    for other in COMPANIES[1:]:
        shared = names["CO-001"] & names[other]
        assert not shared, f"{other} reuses CO-001 client names (must be synthetic, never copies): {shared}"


# ---- helpers for Parts C and D ----------------------------------------------------------------------

def sign_in(api, slug: str, login: str) -> dict:
    r = api.post("/api/auth/otp", role=None, json={"company_slug": slug, "login": login})
    assert r.status_code == 200, r.text
    r = api.post("/api/auth/login", role=None, json={"company_slug": slug, "login": login, "otp": DEMO_OTP})
    assert r.status_code == 200, r.text
    return r.json()


def bearer(session: dict) -> dict:
    return {"Authorization": f"Bearer {session['token']}"}


def as_(api, method: str, url: str, session: dict, **kwargs):
    return api.request(method, url, role=None, headers=bearer(session), **kwargs)


def owners(api) -> dict:
    return {co: sign_in(api, *OWNER_LOGINS[co]) for co in COMPANIES}


def ids(api, session: dict, url: str, key: str) -> set:
    body = as_(api, "GET", url, session).json()
    rows = body["items"] if isinstance(body, dict) else body
    return {row[key] for row in rows}


def scoped_gets() -> list:
    """Every built company GET that needs no path id (query filled where required)."""
    fill = {"/api/search": "q=JC", "/api/dashboard/summary": "period=month"}
    urls = []
    for key, op in OPS.items():
        method, path = key.split(" ", 1)
        if method != "GET" or "{" in path or not built(key):
            continue
        if path.startswith(("/api/platform/", "/api/auth/")):
            continue
        ok = op["responses"].get("200", {}).get("content", {})
        if "application/json" not in ok:
            continue  # SSE / PDF
        required = [p["name"] for p in op.get("parameters", []) if p.get("in") == "query" and p.get("required")]
        urls.append(f"{path}?{fill[path]}" if required else path)
    return sorted(urls)


# ---- Part C: API isolation and tokens (after B1) ----------------------------------------------------

@pytest.mark.parametrize("ready", API_STAGE)
def test_login_gives_a_token_for_exactly_one_company(ready, api):
    for co, (slug, login) in OWNER_LOGINS.items():
        session = sign_in(api, slug, login)
        assert session["token_type"] == "Bearer"
        assert session["company"]["id"] == co
        assert session["user"]["role"] == "owner"
        me = as_(api, "GET", "/api/auth/me", session)
        assert me.status_code == 200, me.text
        assert me.json()["company"]["id"] == co


@pytest.mark.parametrize("ready", API_STAGE)
def test_wrong_otp_or_wrong_company_is_401(ready, api):
    slug, login = OWNER_LOGINS["CO-001"]
    api.post("/api/auth/otp", role=None, json={"company_slug": slug, "login": login})
    r = api.post("/api/auth/login", role=None, json={"company_slug": slug, "login": login, "otp": "000000"})
    assert r.status_code == 401, r.text
    # CO-001's owner cannot sign in to CO-002 with the same login
    other_slug = OWNER_LOGINS["CO-002"][0]
    api.post("/api/auth/otp", role=None, json={"company_slug": other_slug, "login": login})
    r = api.post("/api/auth/login", role=None, json={"company_slug": other_slug, "login": login, "otp": DEMO_OTP})
    assert r.status_code == 401, r.text


@pytest.mark.parametrize("ready", API_STAGE)
def test_company_comes_from_the_token_only(ready, api):
    s = owners(api)
    a, b = s["CO-001"], s["CO-002"]
    mine = ids(api, a, "/api/jobs", "job_card")
    # a company id in the query or a header is ignored
    r = api.get("/api/jobs?company_id=CO-002", role=None, headers={**bearer(a), "X-Company": "CO-002"})
    assert r.status_code == 200, r.text
    assert {j["job_card"] for j in r.json()["items"]} == mine
    # the token wins over X-Role: an owner token with X-Role store still reaches owner-only data
    r = api.get("/api/dashboard/summary?period=month", role="store", headers=bearer(a))
    assert r.status_code == 200, r.text
    assert b["company"]["id"] == "CO-002"


@pytest.mark.parametrize("ready", API_STAGE)
def test_no_endpoint_leaks_another_companys_clients(ready, api):
    s = owners(api)
    client_names = {co: {c["name"] for c in as_(api, "GET", "/api/clients", s[co]).json()} for co in COMPANIES}
    leaks = []
    for co in COMPANIES:
        foreign = set().union(*(client_names[o] for o in COMPANIES if o != co)) - client_names[co]
        assert foreign, "synthetic companies must have their own clients"
        pattern = re.compile("|".join(re.escape(n) for n in sorted(foreign, key=len, reverse=True)))
        for url in scoped_gets():
            r = as_(api, "GET", url, s[co])
            assert r.status_code == 200, f"{co} GET {url}: {r.status_code} {r.text[:200]}"
            hit = pattern.search(r.text)
            if hit:
                leaks.append(f"{co} GET {url} shows {hit.group(0)!r}")
    assert not leaks, "\n".join(leaks)


@pytest.mark.parametrize("ready", API_STAGE)
def test_another_companys_rows_are_404(ready, api):
    s = owners(api)
    a, b = s["CO-001"], s["CO-002"]
    b_jobs = ids(api, b, "/api/jobs", "job_card") - ids(api, a, "/api/jobs", "job_card")
    b_clients = ids(api, b, "/api/clients", "id") - ids(api, a, "/api/clients", "id")
    assert b_jobs and b_clients, "CO-002 needs job cards and clients that CO-001 does not have"
    for jc in sorted(b_jobs)[:3]:
        for url in (f"/api/jobs/{jc}", f"/api/jobs/{jc}/360", f"/api/design/{jc}",
                    f"/api/production/press-setup/{jc}"):
            r = as_(api, "GET", url, a)
            assert r.status_code == 404, f"CO-001 GET {url}: {r.status_code} {r.text[:200]}"
    for cid in sorted(b_clients)[:3]:
        r = as_(api, "GET", f"/api/clients/{cid}", a)
        assert r.status_code == 404, f"CO-001 GET /api/clients/{cid}: {r.status_code}"

    b_findings = ids(api, b, "/api/agents/findings?status=open", "id")
    a_findings = ids(api, a, "/api/agents/findings?status=open", "id")
    for fid in sorted(b_findings - a_findings)[:3]:
        r = as_(api, "POST", f"/api/agents/findings/{fid}/approve", a)
        assert r.status_code == 404, f"CO-001 approve {fid}: {r.status_code}"


@pytest.mark.parametrize("ready", API_STAGE)
def test_one_company_cannot_change_another(ready, fresh_api):
    api = fresh_api
    s = owners(api)
    a, b = s["CO-001"], s["CO-002"]
    b_jobs = sorted(ids(api, b, "/api/jobs", "job_card") - ids(api, a, "/api/jobs", "job_card"))
    b_clients = sorted(ids(api, b, "/api/clients", "id") - ids(api, a, "/api/clients", "id"))
    b_dispatches = sorted(ids(api, b, "/api/dispatch", "id") - ids(api, a, "/api/dispatch", "id"))
    jc, cid = b_jobs[0], b_clients[0]
    before_job = as_(api, "GET", f"/api/jobs/{jc}", b).json()
    before_issues = as_(api, "GET", "/api/store/issues", b).json()

    r = as_(api, "PUT", f"/api/design/{jc}", a, json={"notes": "changed by another company"})
    assert r.status_code == 404, r.text
    r = as_(api, "POST", f"/api/clients/{cid}/release-lock", a, json={"reason": "not my client"})
    assert r.status_code == 404, r.text
    r = as_(api, "POST", "/api/store/issues", a,
            json={"date": "2026-11-20", "job_card": jc, "item_id": "IT-0001", "qty": 10})
    assert r.status_code in (400, 404), r.text
    if b_dispatches:
        r = as_(api, "POST", f"/api/invoices/draft-from-dispatch/{b_dispatches[0]}", a)
        assert r.status_code == 404, r.text
    r = as_(api, "POST", "/api/jobs", a, json={"client_id": cid, "product": "Leak test", "order_qty": 1000,
                                              "rate": 0.5, "po_no": "X/1", "po_date": "2026-11-20"})
    assert r.status_code in (400, 404), f"CO-001 used CO-002's client {cid}: {r.status_code} {r.text}"

    assert as_(api, "GET", f"/api/jobs/{jc}", b).json() == before_job
    assert as_(api, "GET", "/api/store/issues", b).json() == before_issues


@pytest.fixture
def token_api(monkeypatch, request):
    """An API in AUTH_MODE=token: every company call needs a valid token (SPEC 6.2)."""
    monkeypatch.setenv("AUTH_MODE", "token")
    return request.getfixturevalue("fresh_api")


@pytest.mark.parametrize("ready", API_STAGE)
def test_missing_or_bad_token_is_401_in_token_mode(ready, token_api):
    api = token_api
    assert api.get("/api/jobs", role=None).status_code == 401
    assert api.get("/api/jobs", role="owner").status_code == 401, "X-Role alone must not sign in"
    session = sign_in(api, *OWNER_LOGINS["CO-001"])  # otp + login work without a token
    assert as_(api, "GET", "/api/jobs", session).status_code == 200

    token = session["token"]
    tampered = token[:-2] + ("AA" if token[-2:] != "AA" else "BB")
    for bad in (tampered, "abc", ""):
        r = api.get("/api/jobs", role=None, headers={"Authorization": f"Bearer {bad}"})
        assert r.status_code == 401, f"token {bad[:12]!r}: {r.status_code}"
        assert isinstance(r.json().get("detail"), str)

    assert as_(api, "POST", "/api/auth/logout", session).status_code == 200
    assert as_(api, "GET", "/api/jobs", session).status_code == 401, "a logged-out token must stop working"


# ---- Part D: platform and company admin (after B2) --------------------------------------------------

@pytest.mark.parametrize("ready", PLATFORM_STAGE)
def test_platform_admin_sees_companies_not_company_data(ready, api):
    staff = sign_in(api, *PLATFORM_LOGIN)
    assert staff["user"]["role"] == "platform_admin"
    assert staff["company"] is None

    r = as_(api, "GET", "/api/platform/companies", staff)
    assert r.status_code == 200, r.text
    assert set(COMPANIES) <= {c["id"] for c in r.json()["items"]}
    assert as_(api, "GET", "/api/platform/usage", staff).status_code == 200

    for url in ("/api/jobs", "/api/clients", "/api/invoices", "/api/store/stock", "/api/agents/findings"):
        r = as_(api, "GET", url, staff)
        assert r.status_code == 403, f"platform_admin GET {url}: {r.status_code}"
        assert r.json() == {"detail": "forbidden for role platform_admin"}


@pytest.mark.parametrize("ready", PLATFORM_STAGE)
def test_company_admin_cannot_reach_the_platform(ready, api):
    s = owners(api)
    for co in COMPANIES:
        for url in ("/api/platform/companies", "/api/platform/usage"):
            r = as_(api, "GET", url, s[co])
            assert r.status_code == 403, f"{co} owner GET {url}: {r.status_code}"


@pytest.mark.parametrize("ready", PLATFORM_STAGE)
def test_company_admin_sees_only_its_own_company(ready, api):
    s = owners(api)
    users = {}
    for co in COMPANIES:
        profile = as_(api, "GET", "/api/company/profile", s[co])
        assert profile.status_code == 200, profile.text
        assert profile.json()["id"] == co
        users[co] = {u["id"] for u in as_(api, "GET", "/api/company/users", s[co]).json()["items"]}
        assert s[co]["user"]["id"] in users[co]
    for i, co in enumerate(COMPANIES):
        for other in COMPANIES[i + 1:]:
            assert not users[co] & users[other], f"{co} and {other} list the same users"
    # an owner cannot change another company's user
    other_user = sorted(users["CO-002"])[0]
    r = as_(api, "PUT", f"/api/company/users/{other_user}", s["CO-001"], json={"status": "disabled"})
    assert r.status_code == 404, r.text
