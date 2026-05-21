"""
E2E — Ontology Axiom API (/ontology/axioms/…).

Covers the axiom management endpoints: list, get-by-type, save, delete.
Seeded by an OWL import so subClassOf axioms are available.

Covered:
  GET  /ontology/axioms/list
  GET  /ontology/axioms/get-by-type/{axiom_type}
  GET  /ontology/axioms/get-by-class/{class_uri}
  POST /ontology/axioms/save
  POST /ontology/axioms/delete
"""

from __future__ import annotations

import json

import pytest

_SETUP_OWL = """
@prefix owl:  <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@base <http://e2eaxiom.test/> .

<http://e2eaxiom.test/>      a owl:Ontology .
<http://e2eaxiom.test/Animal> a owl:Class ; rdfs:label "Animal" .
<http://e2eaxiom.test/Dog>    a owl:Class ; rdfs:label "Dog" ;
                                rdfs:subClassOf <http://e2eaxiom.test/Animal> .
"""

_ANIMAL_URI = "http://e2eaxiom.test/Animal"
_DOG_URI    = "http://e2eaxiom.test/Dog"

_AXIOM_TYPES = ["SubClassOf", "DisjointWith", "EquivalentClasses"]

_CONTRACT_STATUSES = (200, 400, 403, 404, 422, 502)


def _csrf_headers(context) -> dict:
    cookies = {c["name"]: c["value"] for c in context.cookies()}
    h = {"Content-Type": "application/json"}
    if tok := cookies.get("csrf_token"):
        h["X-CSRF-Token"] = tok
    return h


def _json(resp):
    return json.loads(resp.body())


def _import_owl(page, live_server, headers):
    page.context.request.post(
        f"{live_server}/ontology/import-owl",
        headers=headers,
        data=json.dumps({"content": _SETUP_OWL}),
    )


# ── List / read ───────────────────────────────────────────────────────────────

class TestAxiomList:
    def test_axioms_list_route_mounted(self, page, live_server):
        page.goto(live_server)
        page.wait_for_load_state("domcontentloaded")
        resp = page.request.get(f"{live_server}/ontology/axioms/list")
        assert resp.status != 404, "/ontology/axioms/list is not mounted"

    def test_axioms_list_returns_200(self, page, live_server):
        page.goto(live_server)
        page.wait_for_load_state("domcontentloaded")
        headers = _csrf_headers(page.context)
        _import_owl(page, live_server, headers)
        resp = page.request.get(f"{live_server}/ontology/axioms/list")
        assert resp.status == 200, resp.text()

    def test_axioms_list_is_json(self, page, live_server):
        page.goto(live_server)
        page.wait_for_load_state("domcontentloaded")
        resp = page.request.get(f"{live_server}/ontology/axioms/list")
        payload = _json(resp)
        assert isinstance(payload, (dict, list))

    @pytest.mark.parametrize("axiom_type", _AXIOM_TYPES)
    def test_get_by_type_no_5xx(self, page, live_server, axiom_type):
        page.goto(live_server)
        page.wait_for_load_state("domcontentloaded")
        resp = page.request.get(
            f"{live_server}/ontology/axioms/get-by-type/{axiom_type}"
        )
        assert resp.status < 500, (
            f"get-by-type/{axiom_type} returned 5xx: {resp.text()}"
        )

    def test_get_by_class_no_5xx(self, page, live_server):
        page.goto(live_server)
        page.wait_for_load_state("domcontentloaded")
        headers = _csrf_headers(page.context)
        _import_owl(page, live_server, headers)
        resp = page.request.get(
            f"{live_server}/ontology/axioms/get-by-class/{_DOG_URI}"
        )
        assert resp.status < 500, f"get-by-class returned 5xx: {resp.text()}"


# ── Save / delete ─────────────────────────────────────────────────────────────

class TestAxiomSaveDelete:
    def _post(self, page, live_server, path, body):
        page.goto(live_server)
        page.wait_for_load_state("domcontentloaded")
        return page.context.request.post(
            f"{live_server}{path}",
            headers=_csrf_headers(page.context),
            data=json.dumps(body),
        )

    def _seed(self, page, live_server):
        headers = _csrf_headers(page.context)
        _import_owl(page, live_server, headers)

    def test_save_subclassof_axiom_contract(self, page, live_server):
        self._seed(page, live_server)
        resp = self._post(
            page, live_server,
            "/ontology/axioms/save",
            {
                "axiom_type": "SubClassOf",
                "subject_uri": _DOG_URI,
                "object_uri": _ANIMAL_URI,
            },
        )
        assert resp.status in _CONTRACT_STATUSES, (
            f"axioms/save returned {resp.status}: {resp.text()}"
        )
        assert isinstance(_json(resp), dict)

    def test_delete_nonexistent_axiom_not_5xx(self, page, live_server):
        resp = self._post(
            page, live_server,
            "/ontology/axioms/delete",
            {
                "axiom_type": "SubClassOf",
                "subject_uri": "http://ghost.test/NoClass",
                "object_uri": "http://ghost.test/NoParent",
            },
        )
        assert resp.status < 500, f"axioms/delete 5xx: {resp.text()}"

    def test_save_missing_body_returns_4xx(self, page, live_server):
        resp = self._post(page, live_server, "/ontology/axioms/save", {})
        assert resp.status in (400, 422), (
            f"Expected 400/422 for empty axiom save, got {resp.status}"
        )
