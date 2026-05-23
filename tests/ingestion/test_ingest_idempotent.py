"""Issue #69 Phase C: idempotent retry test.

Uploads a real PDF, lets it complete, retries the SAME job, and verifies
PG/Qdrant/Neo4j show no duplicate rows or extra points.

This is the test the kill-resume scenario reduces to: re-running a job whose
write_log entries are already populated must not insert anything new.
"""
import io
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

PDF = Path("/home/l/rag-dashboard/archive/reference/文档资料和别的ai写的后端代码参考/"
           "深圳市建设工程地方标准/深圳市建设工程计价费率标准（2025）.pdf")
EP = "http://localhost:8002"


def upload(p: Path) -> str:
    boundary = "----k" + os.urandom(8).hex()
    body = io.BytesIO()
    body.write(f"--{boundary}\r\n".encode())
    body.write(f'Content-Disposition: form-data; name="file"; filename="idempotent.pdf"\r\n'.encode())
    body.write(b"Content-Type: application/pdf\r\n\r\n")
    body.write(p.read_bytes())
    body.write(f"\r\n--{boundary}--\r\n".encode())
    req = urllib.request.Request(
        f"{EP}/api/v1/pipeline/upload",
        data=body.getvalue(),
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    return json.loads(urllib.request.urlopen(req, timeout=120).read())["job_id"]


def wait_done(jid, timeout=180):
    for _ in range(timeout):
        time.sleep(1)
        j = json.loads(urllib.request.urlopen(f"{EP}/api/v1/pipeline/job/{jid}", timeout=10).read())
        if j["status"] in ("done", "failed"):
            return j
    return j


def snapshot(jid):
    import psycopg2
    import httpx
    from neo4j import GraphDatabase

    conn = psycopg2.connect("postgresql://rag_user:rag_password@localhost:5432/rag_db")
    cur = conn.cursor()
    cur.execute("SELECT count(*) FROM text_chunks WHERE doc_id=%s", (jid,))
    n_pg = cur.fetchone()[0]
    cur.execute("SELECT chunks_pg, vectors_qdrant, triples_neo4j FROM ingest_jobs WHERE job_id=%s", (jid,))
    counters = cur.fetchone()
    cur.execute("SELECT phase, count(*) FROM ingest_write_log WHERE job_id=%s GROUP BY phase", (jid,))
    wl = dict(cur.fetchall())
    conn.close()

    cli = httpx.Client(transport=httpx.HTTPTransport(proxy=None), timeout=10.0)
    qres = cli.post(
        "http://localhost:6333/collections/document_chunks/points/scroll",
        json={"filter": {"must": [{"key": "doc_id", "match": {"value": jid}}]},
              "limit": 500, "with_payload": False, "with_vector": False},
    ).json()
    n_q = len(qres["result"]["points"])

    drv = GraphDatabase.driver("bolt://localhost:7687", auth=("neo4j", "password"))
    with drv.session() as s:
        n_neo = s.run("MATCH (c:Chunk {doc_id:$d}) RETURN count(c) AS n", d=jid).single()["n"]
        n_ent = s.run(
            "MATCH (c:Chunk {doc_id:$d})-[:MENTIONS]->(e:Entity) RETURN count(*) AS n", d=jid
        ).single()["n"]
    drv.close()
    return {"pg": n_pg, "qdrant": n_q, "neo4j_chunks": n_neo,
            "neo4j_mentions": n_ent, "counters": counters, "write_log": wl}


def main() -> int:
    print("[1] first upload + complete")
    jid = upload(PDF)
    j = wait_done(jid)
    if j["status"] != "done":
        print("    FAIL: first run did not complete:", j); return 1
    print(f"    job={jid}  chunks_pg={j['chunks_pg']}  qdrant={j['vectors_qdrant']}  neo4j={j['triples_neo4j']}")

    print("[2] snapshot after run #1")
    s1 = snapshot(jid)
    print(f"    {s1}")

    print("[3] retry the same job")
    req = urllib.request.Request(f"{EP}/api/v1/pipeline/retry/{jid}", method="POST")
    print("   ", urllib.request.urlopen(req, timeout=15).read().decode())
    j2 = wait_done(jid)
    if j2["status"] != "done":
        print("    FAIL: retry did not complete:", j2); return 1
    print(f"    retry done in ms={j2['duration_ms']}")

    print("[4] snapshot after retry")
    s2 = snapshot(jid)
    print(f"    {s2}")

    expected = j["chunks_pg"]
    ok = (
        s1["pg"] == s2["pg"] == expected
        and s1["qdrant"] == s2["qdrant"] == expected
        and s1["neo4j_chunks"] == s2["neo4j_chunks"] == expected
        and s1["neo4j_mentions"] == s2["neo4j_mentions"]  # equal, not necessarily == expected
    )
    if ok:
        print(f"\nIDEMPOTENT RETRY PASS  (PG/Qdrant/Neo4j chunks all == {expected}, no duplicates)")
        return 0
    print(f"\nIDEMPOTENT RETRY FAIL  expected={expected}\n  before={s1}\n  after ={s2}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
