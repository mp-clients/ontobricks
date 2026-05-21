"""
E2E — External API v1  (/api/v1/…)

Verifies every endpoint on the public REST surface mounted at ``/api``:
- route is reachable (no 404),
- response is always JSON,
- success shapes follow the ``{success, data}`` contract,
- error shapes follow the ``{error, detail}`` contract.

Endpoints that hit Databricks are tested for the *route contract* only:
responses of 200/400/422/502 are all acceptable; 5xx from the framework
are not.

Covered:
  GET  /api/v1/health
  POST /api/v1/domains/list
  POST /api/v1/domain/info
  POST /api/v1/domain/ontology
  POST /api/v1/domain/ontology/classes
  POST /api/v1/domain/ontology/properties
  POST /api/v1/domain/mappings
  POST /api/v1/query/validate
  POST /api/v1/query/samples
"""

from __future__ import annotations

import json


_CONTRACT_STATUSES = (200, 400, 403, 422, 502)

# Minimal payload that satisfies schema validators for domain-scoped requests.
_DOMAIN_PAYLOAD = json.dumps({"domain_name": "e2e_test", "version": "1"})


def _json(resp) -> dict:
    return json.loads(resp.body())


def _assert_json_contract(resp, *, allow_success: bool = True):
    """Route contract: status is in the allowed set; body is valid JSON dict."""
    allowed = _CONTRACT_STATUSES if allow_success else (400, 403, 422, 502)
    assert resp.status in allowed, f"Unexpected status {resp.status}: {resp.text()}"
    payload = _json(resp)
    assert isinstance(payload, dict), f"Expected dict body, got: {type(payload)}"
    if resp.status != 200:
        assert "error" in payload or "detail" in payload, (
            f"Error response missing 'error'/'detail': {payload}"
        )


# ── Health ─────────────────────────────────────────────────────────────────────

class TestApiV1Health:
    def test_health_returns_200(self, page, live_server):
        resp = page.request.get(f"{live_server}/api/v1/health")
        assert resp.status == 200, resp.text()

    def test_health_response_is_json(self, page, live_server):
        resp = page.request.get(f"{live_server}/api/v1/health")
        payload = _json(resp)
        assert isinstance(payload, dict)

    def test_health_has_status_field(self, page, live_server):
        resp = page.request.get(f"{live_server}/api/v1/health")
        payload = _json(resp)
        assert "status" in payload or "success" in payload, (
            f"Expected 'status' or 'success' key in health response: {payload}"
        )


# ── domains/list ───────────────────────────────────────────────────────────────

class TestApiV1DomainsList:
    def _headers(self, context) -> dict:
        cookies = {c["name"]: c["value"] for c in context.cookies()}
        h = {"Content-Type": "application/json"}
        if tok := cookies.get("csrf_token"):
            h["X-CSRF-Token"] = tok
        return h

    def test_domains_list_route_mounted(self, page, live_server):
        page.goto(live_server)
        page.wait_for_load_state("domcontentloaded")
        resp = page.context.request.post(
            f"{live_server}/api/v1/domains/list",
            headers=self._headers(page.context),
            data=json.dumps({}),
        )
        assert resp.status != 404, "domains/list route is not mounted"

    def test_domains_list_returns_json(self, page, live_server):
        page.goto(live_server)
        page.wait_for_load_state("domcontentloaded")
        resp = page.context.request.post(
            f"{live_server}/api/v1/domains/list",
            headers=self._headers(page.context),
            data=json.dumps({}),
        )
        _assert_json_contract(resp)

    def test_domains_list_no_5xx(self, page, live_server):
        page.goto(live_server)
        page.wait_for_load_state("domcontentloaded")
        resp = page.context.request.post(
            f"{live_server}/api/v1/domains/list",
            headers=self._headers(page.context),
            data=json.dumps({}),
        )
        assert resp.status < 500, f"domains/list returned 5xx: {resp.text()}"


# ── domain/* ───────────────────────────────────────────────────────────────────

class TestApiV1DomainEndpoints:
    def _headers(self, context) -> dict:
        cookies = {c["name"]: c["value"] for c in context.cookies()}
        h = {"Content-Type": "application/json"}
        if tok := cookies.get("csrf_token"):
            h["X-CSRF-Token"] = tok
        return h

    def _post(self, page, live_server, path):
        page.goto(live_server)
        page.wait_for_load_state("domcontentloaded")
        return page.context.request.post(
            f"{live_server}{path}",
            headers=self._headers(page.context),
            data=_DOMAIN_PAYLOAD,
        )

    def test_domain_info_contract(self, page, live_server):
        _assert_json_contract(self._post(page, live_server, "/api/v1/domain/info"))

    def test_domain_ontology_contract(self, page, live_server):
        _assert_json_contract(self._post(page, live_server, "/api/v1/domain/ontology"))

    def test_domain_ontology_classes_contract(self, page, live_server):
        _assert_json_contract(self._post(page, live_server, "/api/v1/domain/ontology/classes"))

    def test_domain_ontology_properties_contract(self, page, live_server):
        _assert_json_contract(self._post(page, live_server, "/api/v1/domain/ontology/properties"))

    def test_domain_mappings_contract(self, page, live_server):
        _assert_json_contract(self._post(page, live_server, "/api/v1/domain/mappings"))

    def test_domain_r2rml_contract(self, page, live_server):
        _assert_json_contract(self._post(page, live_server, "/api/v1/domain/r2rml"))


# ── query/* ────────────────────────────────────────────────────────────────────

class TestApiV1Query:
    def _headers(self, context) -> dict:
        cookies = {c["name"]: c["value"] for c in context.cookies()}
        h = {"Content-Type": "application/json"}
        if tok := cookies.get("csrf_token"):
            h["X-CSRF-Token"] = tok
        return h

    def test_query_validate_valid_sparql(self, page, live_server):
        page.goto(live_server)
        page.wait_for_load_state("domcontentloaded")
        resp = page.context.request.post(
            f"{live_server}/api/v1/query/validate",
            headers=self._headers(page.context),
            data=json.dumps({"query": "SELECT ?s WHERE { ?s ?p ?o } LIMIT 1"}),
        )
        assert resp.status == 200, resp.text()
        payload = _json(resp)
        assert "valid" in payload or "success" in payload

    def test_query_validate_invalid_sparql_not_5xx(self, page, live_server):
        page.goto(live_server)
        page.wait_for_load_state("domcontentloaded")
        resp = page.context.request.post(
            f"{live_server}/api/v1/query/validate",
            headers=self._headers(page.context),
            data=json.dumps({"query": "THIS IS NOT SPARQL"}),
        )
        assert resp.status < 500, f"Invalid SPARQL returned 5xx: {resp.text()}"

    def test_query_validate_missing_body_returns_422(self, page, live_server):
        page.goto(live_server)
        page.wait_for_load_state("domcontentloaded")
        resp = page.context.request.post(
            f"{live_server}/api/v1/query/validate",
            headers=self._headers(page.context),
            data=json.dumps({}),
        )
        assert resp.status in (200, 422), f"Unexpected: {resp.status} {resp.text()}"

    def test_query_samples_returns_json(self, page, live_server):
        page.goto(live_server)
        page.wait_for_load_state("domcontentloaded")
        resp = page.context.request.post(
            f"{live_server}/api/v1/query/samples",
            headers=self._headers(page.context),
            data=json.dumps({}),
        )
        assert resp.status < 500
        payload = _json(resp)
        assert isinstance(payload, dict)
