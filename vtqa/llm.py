"""Talking to a language model.

One simple client that speaks the "OpenAI chat completions" format. Ollama, Groq, Gemini,
OpenRouter and many others accept this format, so you only change the URL and model name.
Everything is cached on disk: if you run the same prompt twice it costs nothing the second time.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path

import requests


class LLMError(Exception):
    pass


class BaseLLM:
    name = "base"

    def complete(self, system: str, user: str, temperature: float = 0.0, max_tokens: int = 600) -> str:
        raise NotImplementedError


class OpenAICompat(BaseLLM):
    def __init__(self, base_url: str, model: str, api_key: str = "", sleep: float = 0.0,
                 timeout: float = 180.0, retries: int = 6):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.sleep = sleep
        self.timeout = timeout
        self.retries = retries
        self.name = f"{model}@{self.base_url}"

    def complete(self, system, user, temperature=0.0, max_tokens=600):
        url = self.base_url + "/chat/completions"
        payload = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        last = ""
        for attempt in range(self.retries):
            try:
                r = requests.post(url, json=payload, headers=headers, timeout=self.timeout)
            except requests.RequestException as e:
                last = f"network error: {e}"
                time.sleep(min(2 ** attempt, 30))
                continue
            if r.status_code == 200:
                try:
                    text = r.json()["choices"][0]["message"]["content"] or ""
                except (KeyError, IndexError, ValueError) as e:
                    raise LLMError(f"unexpected reply format: {e}: {r.text[:200]}")
                if self.sleep:
                    time.sleep(self.sleep)
                return text
            if r.status_code in (429, 500, 502, 503, 504):
                wait = r.headers.get("Retry-After")
                try:
                    wait = float(wait)
                except (TypeError, ValueError):
                    wait = min(2 ** attempt * 2, 60)
                last = f"HTTP {r.status_code}"
                time.sleep(wait)
                continue
            raise LLMError(f"HTTP {r.status_code}: {r.text[:300]}")
        raise LLMError(f"gave up after {self.retries} tries ({last})")


class CachedLLM(BaseLLM):
    """Wrap any model with a JSONL cache file."""

    def __init__(self, inner: BaseLLM, path):
        self.inner = inner
        self.name = inner.name
        self.path = Path(path)
        self.cache = {}
        self.hits = 0
        self.calls = 0
        if self.path.exists():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                try:
                    d = json.loads(line)
                    self.cache[d["k"]] = d["v"]
                except (ValueError, KeyError):
                    continue

    def _key(self, system, user, temperature, max_tokens):
        raw = json.dumps([self.inner.name, system, user, temperature, max_tokens], ensure_ascii=False)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def complete(self, system, user, temperature=0.0, max_tokens=600):
        k = self._key(system, user, temperature, max_tokens)
        if k in self.cache:
            self.hits += 1
            return self.cache[k]
        text = self.inner.complete(system, user, temperature, max_tokens)
        self.calls += 1
        self.cache[k] = text
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"k": k, "v": text}, ensure_ascii=False) + "\n")
        return text


class MockLLM(BaseLLM):
    """A fake model for testing the code offline.

    It knows the right SQL and sometimes breaks it on purpose. The numbers it produces say
    NOTHING about real language models. Never put mock results in a CV or a report.
    """

    def __init__(self, examples, error_rate: float = 0.35, seed: int = 0):
        self.name = "mock"
        self.by_question = {ex.question: ex for ex in examples}
        self.error_rate = error_rate
        self.seed = str(seed)

    @staticmethod
    def _break_sql(sql: str, h: int) -> str:
        mode = h % 4
        if mode == 0:  # syntax error
            return sql.replace(" FROM ", " FORM ", 1)
        if mode == 1:  # unknown column
            return sql.replace(" FROM ", ", bogus_col FROM ", 1)
        if mode == 2:  # silently wrong: drop the WHERE clause (or skip the first row)
            cut = re.sub(r"\bWHERE\b.*?(?=\bGROUP BY\b|\bORDER BY\b|\bLIMIT\b|\)|$)", "", sql, count=1, flags=re.S)
            return cut if cut != sql else sql + " LIMIT 1 OFFSET 1"
        # mode 3: flip a comparison
        for a, b in ((">", "<"), ("=", "!=")):
            if a in sql:
                return sql.replace(a, b, 1)
        return sql + " LIMIT 1 OFFSET 1"

    def complete(self, system, user, temperature=0.0, max_tokens=600):
        m = re.search(r"^Question: (.*)$", user, flags=re.M)
        ex = self.by_question.get(m.group(1).strip()) if m else None
        h = int(hashlib.sha256((self.seed + user).encode("utf-8")).hexdigest(), 16)
        bad = (h % 1000) / 1000.0 < self.error_rate
        if "Reply with JSON only" in user:  # the "direct" baseline
            ans = list(ex.gold_answer) if ex else []
            if bad:
                ans = ans[:-1] if len(ans) > 1 else ["unknown"]
            return json.dumps({"answer": ans})
        sql = ex.gold_sql if (ex and ex.gold_sql) else "SELECT 1"
        if bad:
            sql = self._break_sql(sql, h)
        return "```sql\n" + sql + "\n```"
