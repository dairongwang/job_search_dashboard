"""Render pages with a real browser (Playwright + Chromium) for JavaScript-driven job boards.

The app becomes the same client a person uses — a Chromium browser that
executes the page's JavaScript — while staying identifiable and polite:

* the configured User-Agent is sent (robots token ``JobSearchDashboard``),
* robots.txt is checked by the caller before any URL is rendered,
* a 401/403 answer (including bot-protection challenge pages) is reported as
  access denied and **not** retried, disguised or "solved",
* images, media and fonts are not downloaded.

Rendering runs in a child process (``python -m jobsearch_sources.browser``)
so it works from inside Streamlit on every platform and cannot take the UI
down. Install with ``pip install playwright && python -m playwright install chromium``.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import time
from dataclasses import dataclass, field
from typing import Any

from jobsearch_config.schema import SearchSettings

CHALLENGE_MARKERS = ("just a moment", "attention required", "verify you are human", "access denied", "cf-challenge", "captcha")


@dataclass
class Rendered:
    url: str
    status: int
    html: str
    final_url: str = ""
    error: str = ""
    snapshots: list[str] = field(default_factory=list)  # HTML captured after steps marked "snapshot" (final page last)
    steps_done: int = 0
    step_error: str = ""

    @property
    def pages(self) -> list[str]:
        return self.snapshots or ([self.html] if self.html else [])

    @property
    def denied(self) -> bool:
        if self.status in (401, 403, 429):
            return True
        head = (self.html or "")[:4000].lower()
        return self.status == 503 and any(marker in head for marker in CHALLENGE_MARKERS)


def available() -> tuple[bool, str]:
    """Is Playwright installed with a Chromium build? Returns (ok, reason)."""
    if importlib.util.find_spec("playwright") is None:
        return False, "Playwright is not installed (pip install playwright && python -m playwright install chromium)."
    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            try:
                path = pw.chromium.executable_path
            except PlaywrightError as exc:  # pragma: no cover
                return False, f"Playwright's Chromium is not installed ({exc})."
        import os

        if not path or not os.path.exists(path):
            return False, "Playwright's Chromium is not installed (python -m playwright install chromium)."
        return True, ""
    except Exception as exc:  # pragma: no cover - environment specific
        return False, f"Playwright could not start ({exc.__class__.__name__}: {exc})."


def render_pages(
    urls: list[str],
    settings: SearchSettings | None = None,
    delay_seconds: float = 1.0,
    wait_selector: str = "",
    actions: dict[str, list[dict[str, Any]]] | None = None,
) -> list[Rendered]:
    """Render ``urls`` sequentially in one headless Chromium and return their final HTML.

    ``actions`` maps a URL to a list of steps to perform after it loads — the
    way a person uses a site's search form (see ``run_steps`` for the step
    vocabulary). Steps flagged ``"snapshot": true`` capture the page HTML
    after they run, so paginated results can be collected.
    """
    settings = settings or SearchSettings()
    if not urls:
        return []
    payload = {
        "urls": urls,
        "user_agent": settings.user_agent,
        "timeout_ms": int(settings.timeout_seconds * 1000),
        "delay_seconds": float(delay_seconds),
        "wait_selector": wait_selector,
        "actions": actions or {},
    }
    steps = sum(len(v) for v in (actions or {}).values())
    budget = settings.timeout_seconds * (len(urls) + 1 + steps) + delay_seconds * len(urls) + 30
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "jobsearch_sources.browser"],
            input=json.dumps(payload).encode("utf-8"),
            capture_output=True,
            timeout=budget,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return [Rendered(url=u, status=0, html="", error="browser rendering timed out") for u in urls]
    if proc.returncode != 0:
        message = proc.stderr.decode("utf-8", errors="replace").strip().splitlines()
        reason = message[-1] if message else f"exit code {proc.returncode}"
        return [Rendered(url=u, status=0, html="", error=f"browser rendering failed: {reason}") for u in urls]
    try:
        results = json.loads(proc.stdout.decode("utf-8"))
    except json.JSONDecodeError:
        return [Rendered(url=u, status=0, html="", error="browser rendering returned no data") for u in urls]
    return [
        Rendered(
            url=r.get("url", ""),
            status=int(r.get("status") or 0),
            html=r.get("html") or "",
            final_url=r.get("final_url", ""),
            error=r.get("error", ""),
            snapshots=list(r.get("snapshots") or []),
            steps_done=int(r.get("steps_done") or 0),
            step_error=r.get("step_error", ""),
        )
        for r in results
    ]


# ---------------------------------------------------------------------------
# Search-form steps
# ---------------------------------------------------------------------------

STEP_KINDS = ("fill", "select", "click", "check", "press", "wait", "scroll")


def _locator(page: Any, target: Any):
    """Resolve a step target to a Playwright locator.

    ``target`` is a CSS string or an object with one of:
    ``css``, ``text`` (visible text, partial), ``exact_text``, ``placeholder``, ``label``,
    ``button`` (button/link name), ``option`` (listbox option text), ``role`` + ``name``, ``testid``.
    """
    if isinstance(target, str):
        return page.locator(target).first
    if not isinstance(target, dict):
        raise ValueError(f"bad target {target!r}")
    if "css" in target:
        return page.locator(target["css"]).first
    if "placeholder" in target:
        return page.get_by_placeholder(target["placeholder"], exact=bool(target.get("exact"))).first
    if "label" in target:
        return page.get_by_label(target["label"], exact=bool(target.get("exact"))).first
    if "button" in target:
        return page.get_by_role("button", name=target["button"], exact=bool(target.get("exact"))).or_(
            page.get_by_role("link", name=target["button"], exact=bool(target.get("exact")))
        ).first
    if "option" in target:
        return page.get_by_role("option", name=target["option"], exact=bool(target.get("exact"))).or_(
            page.get_by_text(target["option"], exact=bool(target.get("exact")))
        ).first
    if "role" in target:
        return page.get_by_role(target["role"], name=target.get("name"), exact=bool(target.get("exact"))).first
    if "testid" in target:
        return page.get_by_test_id(target["testid"]).first
    if "exact_text" in target:
        return page.get_by_text(target["exact_text"], exact=True).first
    if "text" in target:
        return page.get_by_text(target["text"], exact=False).first
    raise ValueError(f"target needs css/text/placeholder/label/button/option/role: {target!r}")


def run_steps(page: Any, steps: list[dict[str, Any]], timeout_ms: int) -> tuple[list[str], int, str]:
    """Execute search-form steps on a loaded page. Returns (snapshots, steps_done, error)."""
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import TimeoutError as PlaywrightTimeout

    snapshots: list[str] = []
    done = 0
    for index, step in enumerate(steps, start=1):
        kind = next((k for k in STEP_KINDS if k in step), None)
        if kind is None:
            return snapshots, done, f"step {index}: unknown step {step!r}"
        repeat = max(1, int(step.get("repeat") or 1))
        step_timeout = int(step.get("timeout_ms") or timeout_ms)
        for _ in range(repeat):
            try:
                if kind == "fill":
                    loc = _locator(page, step["fill"])
                    loc.click(timeout=step_timeout)
                    loc.fill(str(step.get("value", "")), timeout=step_timeout)
                elif kind == "select":
                    loc = _locator(page, step["select"])
                    value = str(step.get("value", ""))
                    try:
                        loc.select_option(label=value, timeout=step_timeout)
                    except PlaywrightError:
                        loc.select_option(value=value, timeout=step_timeout)
                elif kind == "click":
                    _locator(page, step["click"]).click(timeout=step_timeout)
                elif kind == "check":
                    _locator(page, step["check"]).check(timeout=step_timeout)
                elif kind == "press":
                    key = str(step["press"])
                    if step.get("target"):
                        _locator(page, step["target"]).press(key, timeout=step_timeout)
                    else:
                        page.keyboard.press(key)
                elif kind == "wait":
                    target = step["wait"]
                    if isinstance(target, dict) and "seconds" in target:
                        time.sleep(float(target["seconds"]))
                    elif isinstance(target, (int, float)):
                        time.sleep(float(target))
                    elif target in ("networkidle", "load", "domcontentloaded"):
                        page.wait_for_load_state(target, timeout=step_timeout)
                    else:
                        _locator(page, target).wait_for(timeout=step_timeout)
                elif kind == "scroll":
                    page.mouse.wheel(0, 20000)
                    time.sleep(0.5)
            except (PlaywrightTimeout, PlaywrightError) as exc:
                if step.get("optional"):
                    break
                return snapshots, done, f"step {index} ({kind} {step.get(kind)!r}) failed: {str(exc).splitlines()[0][:160]}"
            if step.get("snapshot"):
                snapshots.append(page.content())
        done += 1
        if step.get("settle_ms"):
            time.sleep(float(step["settle_ms"]) / 1000)
    return snapshots, done, ""


# ---------------------------------------------------------------------------
# Child process
# ---------------------------------------------------------------------------


def _child(payload: dict[str, Any]) -> list[dict[str, Any]]:
    if sys.platform.startswith("win"):  # pragma: no cover
        import asyncio

        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import TimeoutError as PlaywrightTimeout
    from playwright.sync_api import sync_playwright

    results: list[dict[str, Any]] = []
    timeout_ms = int(payload.get("timeout_ms") or 15000)
    delay = float(payload.get("delay_seconds") or 0)
    wait_selector = payload.get("wait_selector") or ""
    actions: dict[str, list[dict[str, Any]]] = payload.get("actions") or {}
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(user_agent=payload.get("user_agent") or None, java_script_enabled=True, locale="en-US")
        context.route("**/*", lambda route: route.abort() if route.request.resource_type in ("image", "media", "font") else route.continue_())
        page = context.new_page()
        last = 0.0
        for url in payload.get("urls", []):
            if last and delay:
                pause = delay - (time.monotonic() - last)
                if pause > 0:
                    time.sleep(pause)
            last = time.monotonic()
            row: dict[str, Any] = {"url": url, "status": 0, "html": "", "final_url": "", "error": "", "snapshots": [], "steps_done": 0, "step_error": ""}
            try:
                response = page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
                row["status"] = response.status if response else 0
                if row["status"] in (401, 403, 429):
                    row["html"] = page.content()[:4000]
                    results.append(row)
                    continue  # denied: do not wait for or interact with challenge pages
                try:
                    if wait_selector:
                        page.wait_for_selector(wait_selector, timeout=timeout_ms)
                    else:
                        page.wait_for_load_state("networkidle", timeout=min(timeout_ms, 8000))
                except PlaywrightTimeout:
                    pass  # use whatever has rendered so far
                steps = actions.get(url) or []
                if steps:
                    snapshots, done, step_error = run_steps(page, steps, timeout_ms)
                    row["snapshots"], row["steps_done"], row["step_error"] = snapshots, done, step_error
                    try:
                        page.wait_for_load_state("networkidle", timeout=min(timeout_ms, 8000))
                    except PlaywrightTimeout:
                        pass
                row["html"] = page.content()
                row["final_url"] = page.url
                if steps:
                    row["snapshots"].append(row["html"])
            except PlaywrightTimeout:
                row["error"] = "timed out while loading"
            except PlaywrightError as exc:
                row["error"] = str(exc).splitlines()[0][:200]
            results.append(row)
        context.close()
        browser.close()
    return results


def main() -> int:  # pragma: no cover - exercised via subprocess in tests
    payload = json.loads(sys.stdin.read() or "{}")
    try:
        results = _child(payload)
    except Exception as exc:  # noqa: BLE001
        sys.stderr.write(f"{exc.__class__.__name__}: {exc}\n")
        return 1
    sys.stdout.write(json.dumps(results))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
