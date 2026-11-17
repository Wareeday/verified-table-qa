"""Run with:  python tests/test_all.py     (no model, no internet needed)

Each test is a small function. If everything is fine you will see 'ALL TESTS PASSED'.
Set VTQA_ONLINE=1 to also test the real WikiTableQuestions download.
"""
import json
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

import run as runner  # noqa: E402
from vtqa.data_mini import load_mini  # noqa: E402
from vtqa.db import load_tables, safe_execute, sanitize_columns  # noqa: E402
from vtqa.methods import extract_sql, parse_direct  # noqa: E402
from vtqa.report import compute_metrics, load_records  # noqa: E402
from vtqa.scoring import normalize, rows_to_answer, same_answer  # noqa: E402
from vtqa.stats import auroc, bootstrap_ci  # noqa: E402
from vtqa.verify import decide  # noqa: E402


def test_sanitize_columns():
    cols = sanitize_columns(["Year", "Year", "2013", "Order", "%", ""])
    assert len(set(cols)) == len(cols), cols
    assert cols[0] == "year" and cols[1] == "year_2"
    assert cols[2] == "c_2013" and cols[3] == "order_col" and cols[4] == "percent"


def test_scoring():
    assert normalize("12,467") == "12467"
    assert normalize(3.0) == "3" and normalize(2.456) == "2.46"
    assert normalize("  Paris ") == "paris"
    assert normalize(None) == "null"
    assert same_answer(["1", "2"], ["2", "1", "1"])
    assert not same_answer(["1"], ["1", "2"])
    assert rows_to_answer([(1, "A"), (2.0, None)]) == ["1", "a", "2", "null"]


def test_sql_safety():
    import pandas as pd
    conn = load_tables({"t": pd.DataFrame({"a": [1, 2, 3]})})
    assert safe_execute(conn, "SELECT COUNT(*) FROM t").rows == [(3,)]
    assert not safe_execute(conn, "DROP TABLE t").ok
    assert not safe_execute(conn, "DELETE FROM t").ok
    assert not safe_execute(conn, "SELECT 1; DROP TABLE t").ok
    assert not safe_execute(conn, "WITH x AS (SELECT 1) DELETE FROM t").ok
    assert safe_execute(conn, "SELECT COUNT(*) FROM t").rows == [(3,)]  # data still there
    assert not safe_execute(conn, "SELECT nope FROM t").ok


def test_sql_timeout():
    import pandas as pd
    conn = load_tables({"t": pd.DataFrame({"a": [1]})})
    t0 = time.time()
    res = safe_execute(conn, "WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x+1 FROM c) SELECT COUNT(*) FROM c",
                       timeout_s=0.5)
    assert not res.ok and "interrupted" in res.error.lower(), res
    assert time.time() - t0 < 5


def test_parsers():
    assert extract_sql("```sql\nSELECT 1\n```") == "SELECT 1"
    assert extract_sql("Plan: use t.\n```SQL\nSELECT a FROM t;\n```") == "SELECT a FROM t;"
    assert extract_sql("<think>hmm SELECT 2</think>SELECT 3 FROM t") == "SELECT 3 FROM t"
    assert extract_sql("I cannot do that") == ""
    assert parse_direct('{"answer": ["Paris", 12]}') == ["paris", "12"]
    assert parse_direct('Sure! {"answer": "7"} done') == ["7"]


def test_mini_dataset():
    a = load_mini(60, seed=7)
    b = load_mini(60, seed=7)
    assert [e.question for e in a] == [e.question for e in b]  # deterministic
    assert len({e.id for e in a}) == len(a) and len({e.question for e in a}) == len(a)
    assert {e.difficulty for e in a} == {"easy", "medium", "hard"}
    conn = load_tables(a[0].tables)
    for e in a:  # the gold SQL must reproduce the gold answer
        res = safe_execute(conn, e.gold_sql)
        assert res.ok and same_answer(rows_to_answer(res.rows), e.gold_answer), e.question
        assert len(e.gold_answer) > 0
    c = load_mini(10, seed=1)
    assert [e.question for e in c] != [e.question for e in a[:10]]


def _cand(sql_ok, ans):
    return {"variant": "x", "sql": "SELECT", "ok": sql_ok, "error": "" if sql_ok else "boom", "answer": ans}


def test_verifier():
    cells = ["alice", "bob", "10"]
    v = decide("Who is first?", [_cand(True, ["alice"]), _cand(True, ["alice"]), _cand(True, ["bob"])], cells, 3)
    assert v.answer == ["alice"] and abs(v.confidence - 2 / 3) < 1e-3 and v.flags == []
    v = decide("Who is first?", [_cand(True, ["alice"])] * 3, cells, 3)
    assert v.confidence == 1.0
    v = decide("Who is first?", [_cand(True, ["alice"]), _cand(False, []), _cand(False, [])], cells, 3)
    assert abs(v.confidence - 1 / 3) < 1e-3  # crashed queries stay in the denominator
    v = decide("Who is first?", [_cand(True, ["zed"])] * 3, cells, 3)
    assert v.flags == ["ungrounded"] and v.confidence == 0.5
    v = decide("How many people are there?", [_cand(True, ["alice"])] * 3, cells, 3)
    assert v.flags == ["type_mismatch"] and v.confidence == 0.5
    v = decide("How many people are there?", [_cand(True, ["7"])] * 3, cells, 3)
    assert v.flags == [] and v.confidence == 1.0
    v = decide("Who?", [_cand(False, []), _cand(True, []), _cand(True, ["null"])], cells, 3)
    assert v.confidence == 0.0 and v.answer == []
    v = decide("Who?", [_cand(True, ["alice"]), _cand(True, ["bob"]), _cand(True, ["10"])], cells, 3)
    assert v.answer == ["alice"]  # a three-way tie goes to the first query


def test_stats():
    x = np.array([1, 0, 1, 1, 0, 1, 1, 1, 0, 1], dtype=float)
    lo, hi = bootstrap_ci(np.mean, x, n_boot=500, seed=1)
    assert lo <= x.mean() <= hi
    assert auroc([0.9, 0.8, 0.2, 0.1], [1, 1, 0, 0]) == 1.0
    assert auroc([0.1, 0.2, 0.8, 0.9], [1, 1, 0, 0]) == 0.0
    assert auroc([0.5, 0.5, 0.5, 0.5], [1, 0, 1, 0]) == 0.5


def _run(tmp, **kw):
    argv = ["--dataset", "mini", "--n", str(kw.get("n", 24)), "--backend", "mock", "--out", str(tmp),
            "--mock-error-rate", str(kw.get("rate", 0.35))]
    return runner.main(argv)


def test_end_to_end_mock():
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "run"
        _run(out)
        for f in ("predictions.jsonl", "report.md", "summary.json", "coverage_curve.png", "failures_to_audit.csv", "meta.json"):
            assert (out / f).exists(), f
        recs = load_records(out)
        assert len(recs) == 24
        assert "MOCK RUN" in (out / "report.md").read_text(encoding="utf-8")
        m = compute_metrics(recs, 0.66, n_boot=200)
        assert 0 <= m["coverage"][0] <= 1 and 0 <= m["vote"][0] <= 1 and 0 <= m["single"][0] <= 1
        assert m["curve"][-1]["coverage"] == 1.0
        before = (out / "predictions.jsonl").read_text(encoding="utf-8")
        _run(out)  # resume: nothing new should be added
        assert (out / "predictions.jsonl").read_text(encoding="utf-8") == before


def test_perfect_and_broken_models():
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "perfect"
        _run(out, rate=0.0)
        m = compute_metrics(load_records(out), 0.66, n_boot=100)
        assert m["single"][0] == 1.0 and m["vote"][0] == 1.0 and m["direct"][0] == 1.0
        assert m["coverage"][0] == 1.0, "the verifier raised a false alarm on perfect answers"
        out = Path(d) / "broken"
        _run(out, rate=1.0)
        m = compute_metrics(load_records(out), 0.66, n_boot=100)
        assert m["single"][0] < 0.35 and m["coverage"][0] < 0.5


def test_http_client_against_local_fake_server():
    """Starts a tiny local server that speaks the chat-completions format, so the real HTTP code path is tested."""
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    from vtqa.llm import MockLLM

    examples = load_mini(6, seed=7)
    fake = MockLLM(examples, error_rate=0.0)
    state = {"calls": 0, "auth": None}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            state["calls"] += 1
            state["auth"] = self.headers.get("Authorization")
            if state["calls"] == 1:  # first call: pretend we are rate limited
                self.send_response(429)
                self.send_header("Retry-After", "0")
                self.end_headers()
                return
            text = fake.complete(body["messages"][0]["content"], body["messages"][1]["content"])
            payload = json.dumps({"choices": [{"message": {"content": text}}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(payload)

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "http"
            os.environ["FAKE_KEY"] = "secret-123"
            runner.main(["--dataset", "mini", "--n", "6", "--base-url", f"http://127.0.0.1:{server.server_port}/v1",
                         "--model", "fake-model", "--api-key-env", "FAKE_KEY", "--out", str(out)])
            recs = load_records(out)
            assert len(recs) == 6 and all(r["single"]["correct"] for r in recs)
            assert state["auth"] == "Bearer secret-123"
            n_calls = state["calls"]
            runner.main(["--dataset", "mini", "--n", "6", "--base-url", f"http://127.0.0.1:{server.server_port}/v1",
                         "--model", "fake-model", "--api-key-env", "FAKE_KEY", "--out", str(Path(d) / "http2")])
            # a different out dir has its own cache, so calls go up again; the same dir would not
            assert state["calls"] > n_calls
            before = state["calls"]
            runner.main(["--dataset", "mini", "--n", "6", "--base-url", f"http://127.0.0.1:{server.server_port}/v1",
                         "--model", "fake-model", "--api-key-env", "FAKE_KEY", "--out", str(out)])
            assert state["calls"] == before, "a finished run should not call the model again"
    finally:
        server.shutdown()


def test_online_wikitq():
    from vtqa.data_wikitq import load_wikitq
    ex = load_wikitq(5, seed=3, cache_dir=str(Path(tempfile.gettempdir()) / "vtqa_wikitq_test"))
    assert len(ex) == 5 and all(e.gold_answer and "t" in e.tables for e in ex)


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        if t.__name__ == "test_online_wikitq" and os.environ.get("VTQA_ONLINE") != "1":
            print("skip", t.__name__, "(set VTQA_ONLINE=1)")
            continue
        t0 = time.time()
        t()
        print(f"ok   {t.__name__}  ({time.time() - t0:.1f}s)")
    print("\nALL TESTS PASSED")
