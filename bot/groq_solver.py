import json
import re
import time
from urllib.request import Request, urlopen
from urllib.parse import urlsplit, urlunsplit
from urllib.error import HTTPError
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout

from bot.config import (
    GROQ_API_KEY,
    GROQ_TEXT_MODEL,
    GROQ_VISION_MODEL,
    GROQ_BASE_URL
)
from bot.diagnostics import log_info, log_warn, log_error, log_quiz

SYSTEM_PROMPT = """You are an expert Oracle Database, SQL, and PL/SQL exam solver.
Analyze the multiple-choice question and options carefully.
Your task is to determine the objectively correct option(s).
Strict rules:
1. Pay strict attention to Oracle SQL syntax, relational algebra, constraints, data modeling, ERD rules, and exact phrasing.
2. Return ONLY a JSON array of 0-based answer indices (e.g., [0] for the 1st option).
3. For multi-select questions include all correct indices (e.g., [0, 2]).
4. Output NOTHING else. No explanations, no markdown formatting, no conversational preamble.
"""


def validate_api():
    if not GROQ_API_KEY or GROQ_API_KEY.startswith("your_"):
        raise RuntimeError("Set GROQ_API_KEY in .env before starting.")
    parsed = urlsplit(GROQ_BASE_URL)
    endpoint = urlunsplit((parsed.scheme, parsed.netloc,
                          parsed.path.rsplit('/chat/completions', 1)[0] + '/models', '', ''))
    request = Request(endpoint, headers={"Authorization": f"Bearer {GROQ_API_KEY}", "User-Agent": "OracleBot/1.0"})
    try:
        with urlopen(request, timeout=20) as response:
            models = {item['id'] for item in json.load(response)['data']}
    except HTTPError as exc:
        raise RuntimeError(f"Groq preflight failed (HTTP {exc.code}). Check API key and account access.") from exc
    missing = {GROQ_TEXT_MODEL, GROQ_VISION_MODEL} - models
    if missing:
        raise RuntimeError(f"Configured Groq models are unavailable: {', '.join(sorted(missing))}. Update .env.")
    log_info("Groq key and configured model availability verified.")

def parse_option_indices(raw_output: str, num_options: int) -> list[int]:
    """
    Parses the model's output into a list of 0-based integer option indices.
    Handles raw digits, JSON arrays, comma-separated lists, and letter choices.
    """
    clean_text = raw_output.strip()
    clean_text = re.sub(r"^```(?:json)?\s*|\s*```$", "", clean_text)

    # 1. Try JSON list extraction
    try:
        data = json.loads(clean_text)
        if isinstance(data, list) and data and all(type(x) is int and 0 <= x < num_options for x in data):
            return sorted(set(data))
        if type(data) is int and 0 <= data < num_options:
            return [data]
    except Exception:
        pass

    # 2. Try regex extraction of 0-based numbers
    found_nums = re.findall(r"\d+", clean_text) if re.fullmatch(r"\d+(?:\s*,\s*\d+)*", clean_text) else []
    valid_nums = []
    for s in found_nums:
        val = int(s)
        if 0 <= val < num_options and val not in valid_nums:
            valid_nums.append(val)
    if valid_nums and len(valid_nums) == len(set(map(int, found_nums))):
        return sorted(valid_nums)

    # 3. Check for letter choices (A, B, C, D) mapped to 0, 1, 2, 3
    letters = re.findall(r"[A-Za-z]", clean_text) if re.fullmatch(r"[A-Za-z](?:\s*,\s*[A-Za-z])*", clean_text) else []
    if letters:
        valid_letters = []
        for l in letters:
            idx = ord(l.upper()) - ord('A')
            if 0 <= idx < num_options and idx not in valid_letters:
                valid_letters.append(idx)
        if valid_letters and len(valid_letters) == len(set(letters)):
            return sorted(valid_letters)

    raise ValueError(f"Could not parse valid option index from Groq response: {raw_output!r}")


def rate_limit_delay(body, headers=None):
    """Groq can report compound durations, such as 1m16.896s."""
    match = re.search(r"try again in\s+((?:[\d.]+(?:ms|h|m|s)\s*)+)", body, re.I)
    if match:
        units = {"h": 3600, "m": 60, "s": 1, "ms": .001}
        return sum(float(value) * units[unit.lower()] for value, unit in
                   re.findall(r"([\d.]+)(ms|h|m|s)", match.group(1), re.I)) + .5
    try:
        return max(float((headers or {}).get("Retry-After", 3.5)), 0) + .5
    except (ValueError, TypeError):
        return 3.5


def solve_mcq(question_text: str, options: list[str], image_b64: str = None, retries: int = 3, multiple: bool = False) -> list[int]:
    """
    Sends question and options to Groq API.
    Uses the configured text or multimodal model. Rejects ambiguous output.
    """
    if not GROQ_API_KEY or GROQ_API_KEY.startswith("your_"):
        raise RuntimeError(
            "GROQ_API_KEY is not set! Please add your key to .env file:\n"
            "GROQ_API_KEY=gsk_your_key_here"
        )

    if not question_text.strip() or len(options) < 2 or retries < 1:
        raise ValueError("A question, at least two options, and positive retries are required.")
    # Build prompt
    options_formatted = "\n".join(f"[{i}] {opt}" for i, opt in enumerate(options))
    user_prompt = f"Question:\n{question_text.strip()}\n\nOptions:\n{options_formatted}\n\nSelect the correct option index (0 to {len(options)-1}):"
    user_prompt += "\nReturn a JSON array of indices. " + ("Multiple answers are allowed." if multiple else "Exactly one answer is allowed.")

    # Select model & construct messages
    if image_b64:
        model = GROQ_VISION_MODEL
        log_quiz(f"Solving question with Groq Vision model: {model}")
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": user_prompt},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{image_b64}"}
                    }
                ]
            }
        ]
    else:
        model = GROQ_TEXT_MODEL
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt}
        ]

    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.0,
        "max_completion_tokens": 2048,
        "reasoning_effort": "low"
    }

    req_data = json.dumps(payload).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "User-Agent": "OracleBot/1.0"
    }

    last_error = None
    attempt = 1
    rate_limits = 0
    rate_waited = 0.0
    while attempt <= retries:
        try:
            start_t = time.perf_counter()
            req = Request(GROQ_BASE_URL, data=req_data, headers=headers, method="POST")
            with urlopen(req, timeout=30) as resp:
                result = json.loads(resp.read().decode("utf-8"))
            elapsed = time.perf_counter() - start_t

            raw_answer = result["choices"][0]["message"]["content"].strip()
            log_quiz(f"Groq answered in {elapsed:.2f}s: {raw_answer!r}")

            indices = parse_option_indices(raw_answer, len(options))
            if not multiple and len(indices) != 1:
                raise ValueError("Multiple indices returned for a single-choice question.")
            return indices

        except HTTPError as e:
            err_body = e.read().decode("utf-8", errors="replace")
            last_error = f"Groq HTTP {e.code}: {err_body[:300]}"
            log_warn(f"Groq attempt {attempt} failed: {last_error}")
            if e.code not in (408, 429) and e.code < 500:
                raise RuntimeError(last_error) from e
            if e.code == 429:
                sleep_sec = max(rate_limit_delay(err_body, e.headers), 3.5)
                # Rate limiting is temporary and does not consume answer retries.
                # Bound waiting so an unavailable account still pauses clearly.
                if rate_limits >= 20 or rate_waited + sleep_sec > 900:
                    raise RuntimeError("Groq rate-limit wait budget exhausted; resume after quota recovers.") from e
                rate_limits += 1
                rate_waited += sleep_sec
                log_warn(f"Rate limited by Groq. Waiting {sleep_sec:.1f}s before retrying the same question...")
                time.sleep(sleep_sec)
                continue
            if attempt < retries:
                time.sleep(1.5)
            attempt += 1
        except Exception as e:
            last_error = str(e)
            log_warn(f"Groq attempt {attempt} error: {last_error}")
            if attempt < retries:
                time.sleep(1.5)
            attempt += 1

    raise RuntimeError(f"All Groq API attempts failed. Last error: {last_error}")


def solve_with_session(page, question_text, options, image_b64=None, multiple=False):
    from bot.session import maintain_session
    # HTTP runs in a worker; every browser operation stays on the main thread.
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(solve_mcq, question_text, options, image_b64, multiple=multiple)
        while True:
            maintain_session(page)
            if future.done():
                return future.result()
            try:
                return future.result(timeout=0.25)
            except FutureTimeout:
                if future.done():
                    return future.result()
                page.wait_for_timeout(250)
