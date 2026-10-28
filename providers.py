"""Model providers: an OpenAI-compatible client and deterministic simulated models (flagged synthetic)."""
import json
import time
import urllib.error
import urllib.parse
import urllib.request

from .common import sha256_text
from .grading import format_number, wrong_answer

RETRY_STATUS = {408, 429, 500, 502, 503, 504}
MOCK_POLICIES = ("perfect", "calibrated", "overconfident", "underconfident", "format_breaker")
_CONF_BY_DIFFICULTY = {"easy": 90, "medium": 70, "hard": 40}


class ProviderError(RuntimeError):
    pass


def check_endpoint_security(base: str):
    u = urllib.parse.urlparse(base)
    if u.scheme != "https" and u.hostname not in ("localhost", "127.0.0.1", "::1"):
        raise SystemExit("Refusing to send an API key over non-HTTPS to a remote host: " + base)


def parse_chat_response(parsed) -> str:
    try:
        content = parsed["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        raise ValueError("response has no choices[0].message.content")
    if isinstance(content, list):
        content = "".join(p.get("text", "") for p in content if isinstance(p, dict))
    if not isinstance(content, str) or not content.strip():
        raise ValueError("response content is empty or not text (refusal or filtered output?)")
    return content


class OpenAICompatible:
    kind, synthetic = "openai-compatible", False

    def __init__(self, base_url, api_key, model, temperature=0.0, max_tokens=None, timeout=90, retries=3, backoff=2.0, sleep=time.sleep):
        check_endpoint_security(base_url)
        self.base, self.key, self.model = base_url.rstrip("/"), api_key, model
        self.temperature, self.max_tokens, self.timeout = temperature, max_tokens, timeout
        self.retries, self.backoff, self.sleep = retries, backoff, sleep

    @property
    def model_requested(self):
        return self.model

    def _post(self, payload):
        data, last = json.dumps(payload).encode(), None
        for attempt in range(1, self.retries + 2):
            req = urllib.request.Request(self.base + "/chat/completions", data=data, method="POST",
                                         headers={"Content-Type": "application/json", "Authorization": "Bearer " + self.key})
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    return json.loads(r.read().decode("utf-8")), attempt
            except urllib.error.HTTPError as e:
                last = ProviderError(f"HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:300]}")
                if e.code not in RETRY_STATUS:
                    raise last
            except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
                last = e
            if attempt <= self.retries:
                self.sleep(self.backoff * 2 ** (attempt - 1))
        raise last

    def chat(self, messages, ctx=None) -> dict:
        payload = {"model": self.model, "temperature": self.temperature, "messages": messages}
        if self.max_tokens:
            payload["max_tokens"] = self.max_tokens
        parsed, attempts = self._post(payload)
        return {"text": parse_chat_response(parsed), "model": parsed.get("model"), "usage": parsed.get("usage"),
                "response_id": parsed.get("id"), "attempts": attempts}


def _u(qid: str, salt: str) -> float:
    """Deterministic pseudo-random number in [0, 1) from the question id."""
    return int(sha256_text(f"{salt}:{qid}")[:8], 16) / 2 ** 32


def mock_reply(policy: str, q: dict, style: str) -> str:
    """Simulated model behaviour with a *known* calibration property, used to validate the pipeline."""
    right = format_number(q["answer"]) if q["answer_type"] == "number" else q["answer"]
    u = _u(q["id"], policy)
    if policy == "perfect":
        ok, conf = True, 100
    elif policy == "overconfident":
        ok, conf = u < 0.6, 95
    elif policy == "underconfident":
        ok, conf = u < 0.9, 50
    elif policy == "calibrated":
        conf = _CONF_BY_DIFFICULTY[q["difficulty"]]
        ok = u < conf / 100
    elif policy == "format_breaker":
        return f"I believe the answer is {right}."
    else:
        raise SystemExit(f"Unknown mock policy {policy!r}; choose from {list(MOCK_POLICIES)}")
    pre = "Let me think step by step.\nAnswer: draft\nConfidence: 10\n" if style == "cot" else ""  # earlier lines must be ignored
    return f"{pre}Answer: {right if ok else wrong_answer(q)}\nConfidence: {conf}"


class MockProvider:
    kind, synthetic = "mock", True

    def __init__(self, policy: str):
        if policy not in MOCK_POLICIES:
            raise SystemExit(f"Unknown mock policy {policy!r}; choose from {list(MOCK_POLICIES)}")
        self.policy = policy

    @property
    def model_requested(self):
        return f"mock:{self.policy}"

    def chat(self, messages, ctx=None) -> dict:
        return {"text": mock_reply(self.policy, ctx["question"], ctx["style"]), "model": self.model_requested,
                "usage": None, "response_id": None, "attempts": 1}
