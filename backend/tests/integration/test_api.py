"""End-to-end API flow: auth -> batch upload -> async ingestion -> dedup/versioning -> search with filters
-> chat (JSON + SSE) with citations -> conversation follow-up -> cache -> analytics -> RBAC -> rate limit -> delete."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration
CORPUS = Path(__file__).resolve().parents[2] / "eval" / "corpus"
STATE: dict = {}


def H(token):
    return {"Authorization": f"Bearer {token}"}


async def test_health(client):
    assert (await client.get("/health")).json()["status"] == "ok"
    r = await client.get("/api/v1/health/ready")
    assert r.status_code == 200, r.text
    assert all(c["ok"] for c in r.json()["checks"].values())


async def test_register_login_roles(client):
    r = await client.post("/api/v1/auth/register", json={"email": "admin@example.com", "password": "admin-pass-123"})
    assert r.status_code == 201 and r.json()["user"]["role"] == "admin"
    r = await client.post("/api/v1/auth/register", json={"email": "viewer@example.com", "password": "viewer-pass-123"})
    assert r.json()["user"]["role"] == "viewer"
    STATE["viewer"] = r.json()["access_token"]
    assert (await client.post("/api/v1/auth/register", json={"email": "admin@example.com", "password": "x" * 9})).status_code == 409
    bad = await client.post("/api/v1/auth/login", data={"username": "admin@example.com", "password": "wrong-pass"})
    assert bad.status_code == 401
    r = await client.post("/api/v1/auth/login", data={"username": "admin@example.com", "password": "admin-pass-123"})
    STATE["admin"] = r.json()["access_token"]
    assert (await client.get("/api/v1/auth/me", headers=H(STATE["admin"]))).json()["email"] == "admin@example.com"
    assert (await client.get("/api/v1/documents")).status_code == 401


async def test_viewer_cannot_upload(client):
    files = [("files", ("x.txt", b"hello world", "text/plain"))]
    assert (await client.post("/api/v1/documents", files=files, headers=H(STATE["viewer"]))).status_code == 403


async def test_batch_upload_and_ingestion(client):
    from app.ingestion.worker import wait_inline_jobs
    names = ["travel_expense_policy_2023.pdf", "travel_expense_policy_2024.pdf", "employee_handbook.pdf",
             "information_security_policy_2024.docx", "customer_support_sla.md", "incident_response_runbook.txt"]
    meta = {"travel_expense_policy_2023.pdf": {"category": "Finance", "doc_date": "2023-02-01"},
            "travel_expense_policy_2024.pdf": {"category": "Finance", "doc_date": "2024-03-15"},
            "employee_handbook.pdf": {"category": "HR", "doc_date": "2024-01-08"}}
    files = [("files", (n, (CORPUS / n).read_bytes())) for n in names] + [("files", ("bad.exe", b"MZ"))]
    r = await client.post("/api/v1/documents", files=files, data={"metadata": json.dumps(meta), "author": "QA Team"},
                          headers=H(STATE["admin"]))
    assert r.status_code == 202, r.text
    statuses = {x["filename"]: x["status"] for x in r.json()}
    assert statuses.pop("bad.exe") == "rejected"
    assert set(statuses.values()) == {"created"}
    await wait_inline_jobs()
    docs = (await client.get("/api/v1/documents", headers=H(STATE["viewer"]))).json()
    assert docs["total"] == 6
    by_name = {d["filename"]: d for d in docs["items"]}
    assert all(d["status"] == "ready" and d["chunk_count"] > 0 for d in docs["items"]), docs
    assert by_name["travel_expense_policy_2024.pdf"]["category"] == "Finance"
    assert by_name["travel_expense_policy_2024.pdf"]["page_count"] == 3
    assert by_name["employee_handbook.pdf"]["author"] == "QA Team"  # form value applied to all files
    STATE["docs"] = by_name
    chunks = (await client.get(f"/api/v1/documents/{by_name['customer_support_sla.md']['id']}/chunks",
                               headers=H(STATE["viewer"]))).json()
    assert any(c["chunk_type"] == "table" for c in chunks)
    f = await client.get(f"/api/v1/documents/{by_name['employee_handbook.pdf']['id']}/file", headers=H(STATE["viewer"]))
    assert f.status_code == 200 and f.content[:4] == b"%PDF"
    facets = (await client.get("/api/v1/documents/facets", headers=H(STATE["viewer"]))).json()
    assert {"Finance", "HR"} <= set(facets["categories"])


async def test_duplicate_and_new_version(client):
    from app.ingestion.worker import wait_inline_jobs
    name = "incident_response_runbook.txt"
    dup = await client.post("/api/v1/documents", files=[("files", ("copy.txt", (CORPUS / name).read_bytes()))],
                            headers=H(STATE["admin"]))
    assert dup.json()[0]["status"] == "duplicate"
    new = (CORPUS / name).read_bytes() + b"\n\n9. Contact\n\nThe SRE pager number is 555-0199.\n"
    upd = await client.post("/api/v1/documents", files=[("files", (name, new))], headers=H(STATE["admin"]))
    assert upd.json()[0]["status"] == "updated" and upd.json()[0]["document"]["version"] == 2
    await wait_inline_jobs()
    r = await client.post("/api/v1/search", headers=H(STATE["viewer"]),
                          json={"query": "SRE pager number", "config": {"mode": "bm25", "rerank": False}})
    top = r.json()["results"][0]
    assert top["filename"] == name and "555-0199" in top["text"]
    # old version's chunks are gone: number of chunks for the doc equals the new chunk_count
    doc = (await client.get(f"/api/v1/documents/{upd.json()[0]['document']['id']}", headers=H(STATE["viewer"]))).json()
    chunks = (await client.get(f"/api/v1/documents/{doc['id']}/chunks", headers=H(STATE["viewer"]))).json()
    assert len(chunks) == doc["chunk_count"]


@pytest.mark.parametrize("mode,rerank", [("dense", False), ("bm25", False), ("hybrid", False), ("hybrid", True)])
async def test_search_modes(client, mode, rerank):
    r = await client.post("/api/v1/search", headers=H(STATE["viewer"]), json={
        "query": "How many weeks of parental leave do birth parents get?",
        "config": {"mode": mode, "rerank": rerank, "top_k": 3}})
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["results"]) == 3
    assert body["results"][0]["filename"] == "employee_handbook.pdf"
    if rerank:
        assert "rerank" in body["results"][0]["scores"] and "rerank_ms" in body["timings_ms"]
    if mode == "hybrid":
        assert "rrf" in body["results"][0]["scores"]


async def test_metadata_filters_select_version(client):
    q = {"query": "nightly hotel cap Tier 1 New York", "config": {"mode": "hybrid", "rerank": True, "top_k": 3}}
    for year, cap in (("2023", "275"), ("2024", "320")):
        r = await client.post("/api/v1/search", headers=H(STATE["viewer"]), json={
            **q, "filters": {"date_from": f"{year}-01-01", "date_to": f"{year}-12-31", "categories": ["Finance"]}})
        res = r.json()["results"]
        assert res and all(x["filename"] == f"travel_expense_policy_{year}.pdf" for x in res)
        assert any(cap in x["text"] for x in res)
    # use_filters=false ignores filters (used to compare configurations)
    r = await client.post("/api/v1/search", headers=H(STATE["viewer"]), json={
        **q, "config": {**q["config"], "use_filters": False}, "filters": {"categories": ["HR"]}})
    assert r.json()["filters"] == {}


async def test_chat_with_citations_and_followup(client):
    r = await client.post("/api/v1/chat", headers=H(STATE["viewer"]), json={
        "message": "How long is parental leave for birth parents?", "filters": {"categories": ["HR"]}})
    assert r.status_code == 200, r.text
    body = r.json()
    assert not body["abstained"] and body["citations"]
    c = body["citations"][0]
    assert c["filename"] == "employee_handbook.pdf" and c["page_start"] and c["quote"]
    assert body["sources"] and body["usage"]["prompt_tokens"] > 0 and body["cache_hit"] is False
    STATE["conv"] = body["conversation_id"]
    # follow-up uses history -> standalone query rewrite
    r2 = await client.post("/api/v1/chat", headers=H(STATE["viewer"]), json={
        "message": "and for non-birth parents?", "conversation_id": STATE["conv"]})
    assert r2.json()["standalone_query"] != "and for non-birth parents?"
    conv = (await client.get(f"/api/v1/conversations/{STATE['conv']}", headers=H(STATE["viewer"]))).json()
    assert [m["role"] for m in conv["messages"]] == ["user", "assistant", "user", "assistant"]
    assert conv["messages"][1]["citations"]
    # other users cannot read it
    assert (await client.get(f"/api/v1/conversations/{STATE['conv']}", headers=H(STATE["admin"]))).status_code == 404


async def test_chat_cache_hit(client):
    body = {"message": "What is the uptime commitment for Standard customers?"}
    first = (await client.post("/api/v1/chat", headers=H(STATE["admin"]), json=body)).json()
    second = (await client.post("/api/v1/chat", headers=H(STATE["admin"]), json=body)).json()
    assert first["cache_hit"] is False and second["cache_hit"] is True
    assert second["answer"] == first["answer"] and second["citations"] == first["citations"]


async def test_chat_stream_sse(client):
    events = []
    async with client.stream("POST", "/api/v1/chat/stream", headers=H(STATE["admin"]),
                             json={"message": "What does error HX-503 mean?", "use_cache": False}) as r:
        assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
        ev = None
        async for line in r.aiter_lines():
            if line.startswith("event:"):
                ev = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                events.append((ev, json.loads(line.split(":", 1)[1])))
    kinds = [e for e, _ in events]
    assert kinds[0] == "conversation" and "sources" in kinds and kinds[-1] == "done"
    assert kinds.count("token") > 3
    done = events[-1][1]
    tokens = "".join(d["text"] for e, d in events if e == "token")
    assert done["answer"].strip() == tokens.strip()
    assert done["citations"][0]["filename"] == "incident_response_runbook.txt"


async def test_relevance_gate_abstains(client):
    r = await client.post("/api/v1/chat", headers=H(STATE["admin"]), json={
        "message": "Which spaceship model does the Martian embassy prefer for interstellar lunar picnics?"})
    body = r.json()
    assert body["abstained"] is True and body["citations"] == []


async def test_analytics_and_query_log(client):
    assert (await client.get("/api/v1/analytics/summary", headers=H(STATE["viewer"]))).status_code == 403
    s = (await client.get("/api/v1/analytics/summary", headers=H(STATE["admin"]))).json()
    assert s["queries"] >= 8 and s["by_endpoint"]["chat"] >= 5 and s["latency_ms"]["p95"] is not None
    assert 0 < s["cache_hit_rate"] < 1 and s["tokens"]["prompt"] > 0
    logs = (await client.get("/api/v1/analytics/queries?limit=5", headers=H(STATE["admin"]))).json()
    assert logs[0]["retrieved"] and "total_ms" in logs[0]


async def test_rate_limit(client):
    codes = []
    for i in range(10):
        r = await client.post("/api/v1/chat", headers=H(STATE["viewer"]), json={"message": f"rate limit probe {i}"})
        codes.append(r.status_code)
    assert 429 in codes


async def test_delete_document(client):
    doc = STATE["docs"]["customer_support_sla.md"]
    assert (await client.delete(f"/api/v1/documents/{doc['id']}", headers=H(STATE["viewer"]))).status_code == 403
    assert (await client.delete(f"/api/v1/documents/{doc['id']}", headers=H(STATE["admin"]))).status_code == 204
    r = await client.post("/api/v1/search", headers=H(STATE["admin"]), json={
        "query": "Mission Critical P1 response time", "config": {"top_k": 10}})
    assert all(x["filename"] != "customer_support_sla.md" for x in r.json()["results"])
