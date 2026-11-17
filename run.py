"""Run the experiment.   python run.py --help   to see every option."""
from __future__ import annotations

import argparse
import json
import os
import platform
import sys
import time
from pathlib import Path

from vtqa import __version__
from vtqa.db import all_cells, describe_schema, load_tables
from vtqa.llm import CachedLLM, LLMError, MockLLM, OpenAICompat
from vtqa.methods import Config, process_example
from vtqa.report import make_report

PRESETS = {  # base url, environment variable that holds the key, default key
    "ollama": ("http://localhost:11434/v1", "OLLAMA_API_KEY", "ollama"),
    "groq": ("https://api.groq.com/openai/v1", "GROQ_API_KEY", None),
    "gemini": ("https://generativelanguage.googleapis.com/v1beta/openai/", "GEMINI_API_KEY", None),
    "openrouter": ("https://openrouter.ai/api/v1", "OPENROUTER_API_KEY", None),
}


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Verified Table QA: text-to-SQL with voting and abstention.")
    p.add_argument("--dataset", choices=["mini", "wikitq"], default="mini")
    p.add_argument("--n", type=int, default=60, help="number of questions")
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--backend", choices=["openai", "mock"], default="openai",
                   help="'openai' = any OpenAI-compatible server; 'mock' = fake model for testing the code")
    p.add_argument("--preset", choices=sorted(PRESETS), help="shortcut for --base-url and the key variable")
    p.add_argument("--base-url", help="e.g. http://localhost:11434/v1")
    p.add_argument("--model", help="model name exactly as your provider calls it")
    p.add_argument("--api-key-env", help="name of the environment variable that holds your API key")
    p.add_argument("--k", type=int, default=3, help="SQL queries per question (3 = three prompt styles)")
    p.add_argument("--tau", type=float, default=0.66, help="answer only if confidence >= tau; 0.66 = at least 2 of 3 queries agree (choose BEFORE you look)")
    p.add_argument("--no-samples", action="store_true", help="show the model the schema only, without example rows")
    p.add_argument("--skip-direct", action="store_true", help="skip the direct-from-table baseline (saves calls)")
    p.add_argument("--max-table-rows", type=int, default=60, help="wikitq: skip tables longer than this")
    p.add_argument("--sleep", type=float, default=0.0, help="seconds to wait after each call (free tiers have limits)")
    p.add_argument("--mock-error-rate", type=float, default=0.35)
    p.add_argument("--out", default="results/run1")
    return p.parse_args(argv)


def build_llm(args, examples):
    out = Path(args.out)
    if args.backend == "mock":
        inner = MockLLM(examples, error_rate=args.mock_error_rate, seed=args.seed)
        return inner, "mock"
    base, key_env, key_default = args.base_url, args.api_key_env, None
    if args.preset:
        pb, pk, key_default = PRESETS[args.preset]
        base = base or pb
        key_env = key_env or pk
    if not base or not args.model:
        sys.exit("Please give --model and either --preset (ollama/groq/gemini/openrouter) or --base-url.\n"
                 "Example: python run.py --preset ollama --model qwen2.5-coder:7b")
    key = os.environ.get(key_env, "") if key_env else ""
    key = key or (key_default or "")
    if args.preset in ("groq", "gemini", "openrouter") and not key:
        sys.exit(f"No API key found. Set the environment variable {key_env} first (see README).")
    inner = OpenAICompat(base, args.model, api_key=key, sleep=args.sleep)
    return inner, args.model


def main(argv=None):
    args = parse_args(argv)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    print(f"Loading dataset '{args.dataset}' ...")
    if args.dataset == "mini":
        from vtqa.data_mini import load_mini
        examples = load_mini(args.n, args.seed)
    else:
        from vtqa.data_wikitq import load_wikitq
        examples = load_wikitq(args.n, args.seed, max_rows=args.max_table_rows)
    print(f"  {len(examples)} questions loaded")

    inner, model_name = build_llm(args, examples)
    llm = CachedLLM(inner, out / "llm_cache.jsonl")
    if args.backend == "mock":
        print("\n" + "!" * 70 + "\n  MOCK RUN: fake model, results are meaningless. For testing only.\n" + "!" * 70 + "\n")
    else:
        try:  # quick connection test, so a wrong URL fails now and not after an hour
            llm.complete("You are a test.", "Reply with the single word: OK", max_tokens=10)
        except LLMError as e:
            sys.exit(f"Could not talk to the model: {e}\nCheck --base-url / --model / your key and that the server is running.")

    cfg = Config(k=args.k, tau=args.tau, skip_direct=args.skip_direct, n_sample_rows=0 if args.no_samples else 3)
    meta = {"dataset": args.dataset, "n": len(examples), "seed": args.seed, "backend": args.backend,
            "model": model_name, "k": args.k, "tau": args.tau, "skip_direct": args.skip_direct,
            "no_samples": args.no_samples, "version": __version__, "python": platform.python_version(),
            "started": time.strftime("%Y-%m-%d %H:%M:%S")}
    (out / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

    pred_path = out / "predictions.jsonl"
    done = set()
    if pred_path.exists():
        for line in pred_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                done.add(json.loads(line)["id"])
    todo = [e for e in examples if e.id not in done]
    calls = len(todo) * (cfg.k + (0 if cfg.skip_direct else 1))
    print(f"{len(done)} already done, {len(todo)} to do, up to {calls} model calls (cached ones are free).")

    dbs = {}
    t0 = time.time()
    with pred_path.open("a", encoding="utf-8") as f:
        for i, ex in enumerate(todo, 1):
            if ex.table_key not in dbs:
                conn = load_tables(ex.tables)
                dbs[ex.table_key] = (conn, describe_schema(conn, cfg.n_sample_rows), all_cells(conn))
            conn, schema, cells = dbs[ex.table_key]
            rec = process_example(llm, ex, conn, schema, cells, cfg)
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            f.flush()
            if i % 5 == 0 or i == len(todo):
                rate = (time.time() - t0) / i
                print(f"  {i}/{len(todo)} questions  (~{rate * (len(todo) - i) / 60:.1f} min left)")
    report = make_report(out, args.tau)
    print(f"\nDone. Open {report}")
    return out


if __name__ == "__main__":
    main()
