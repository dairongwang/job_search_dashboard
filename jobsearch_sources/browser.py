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

import importlib
import importlib.util
import json
import os
import subprocess
import sys
import threading
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
    matched: str = ""  # key of the search-form strategy candidate whose fingerprint matched (plans only)
    initial_html: str = ""  # page HTML after load, before any step ran (plans only)

    @property
    def pages(self) -> list[str]:
        return self.snapshots or ([self.html] if self.html else [])

    @property
    def denied(self) -> bool:
        if self.status in (401, 403, 429):
            return True
        head = (self.html or "")[:4000].lower()
        return self.status == 503 and any(marker in head for marker in CHALLENGE_MARKERS)


AUTO_INSTALL_ENV = "JOB_SEARCH_AUTO_INSTALL_BROWSER"  # "0" disables the automatic install below
_install_lock = threading.Lock()
_install_attempted = False
_install_log: list[str] = []


def _probe() -> tuple[bool, str]:
    """Is Playwright importable with a Chromium build present? Returns (ok, reason) — never installs anything."""
    importlib.invalidate_caches()
    if importlib.util.find_spec("playwright") is None:
        return False, "the 'playwright' package is not installed (python -m pip install playwright)."
    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            try:
                path = pw.chromium.executable_path
            except PlaywrightError as exc:  # pragma: no cover
                return False, f"Playwright's Chromium is not installed ({exc})."
        if not path or not os.path.exists(path):
            return False, "Playwright's Chromium browser is not installed (python -m playwright install chromium)."
        return True, ""
    except Exception as exc:  # pragma: no cover - environment specific
        return False, f"Playwright could not start ({exc.__class__.__name__}: {exc})."


def auto_install_enabled() -> bool:
    return os.environ.get(AUTO_INSTALL_ENV, "1").strip().lower() not in ("0", "false", "no", "off")


def _run(cmd: list[str], timeout: int) -> tuple[bool, str]:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"{' '.join(cmd[-3:])}: {exc}"
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "").strip().splitlines()
        return False, f"{' '.join(cmd[-3:])} failed: {tail[-1] if tail else 'exit code ' + str(proc.returncode)}"
    return True, ""


def ensure_installed(log: Any = None, force: bool = False) -> tuple[bool, str]:
    """Install what headless rendering needs — the ``playwright`` package and its Chromium build — if missing.

    Runs ``python -m pip install playwright`` and ``python -m playwright install chromium``
    with the *current* interpreter, so the user never has to do it by hand. Each
    process tries at most once (``force`` retries). Returns ``available()``'s verdict.
    """
    global _install_attempted
    ok, reason = _probe()
    if ok:
        return True, ""
    with _install_lock:
        if _install_attempted and not force:
            return False, reason + (f" Automatic install: {'; '.join(_install_log)}" if _install_log else "")
        _install_attempted = True
        _install_log.clear()
        say = log or (lambda message: None)
        if importlib.util.find_spec("playwright") is None:
            say("Installing the 'playwright' package (python -m pip install playwright)…")
            done, error = _run([sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "playwright>=1.45"], timeout=900)
            if not done:
                _install_log.append(error)
                return False, f"could not install the 'playwright' package automatically — {error}. Run: python -m pip install playwright && python -m playwright install chromium"
            _install_log.append("installed the playwright package")
            importlib.invalidate_caches()
        ok, reason = _probe()
        if ok:
            return True, ""
        say("Downloading Chromium for Playwright (python -m playwright install chromium) — first time only, about 150 MB…")
        done, error = _run([sys.executable, "-m", "playwright", "install", "chromium"], timeout=1800)
        if not done:
            _install_log.append(error)
            return False, f"could not download Chromium automatically — {error}. Run: python -m playwright install chromium"
        _install_log.append("installed Chromium")
        ok, reason = _probe()
        return ok, ("" if ok else reason)


def available(install: bool | None = None) -> tuple[bool, str]:
    """Is Playwright installed with a Chromium build? Returns (ok, reason).

    When something is missing and automatic installation is enabled
    (``JOB_SEARCH_AUTO_INSTALL_BROWSER`` != 0; the default), it is installed
    on the spot so searches and form tests work without manual setup.
    """
    ok, reason = _probe()
    if ok:
        return True, ""
    if install is None:
        install = auto_install_enabled()
    if not install:
        return False, reason
    return ensure_installed()


def render_pages(
    urls: list[str],
    settings: SearchSettings | None = None,
    delay_seconds: float = 1.0,
    wait_selector: str = "",
    actions: dict[str, list[dict[str, Any]]] | None = None,
    plans: dict[str, dict[str, Any]] | None = None,
) -> list[Rendered]:
    """Render ``urls`` sequentially in one headless Chromium and return their final HTML.

    ``actions`` maps a URL to a list of steps to perform after it loads — the
    way a person uses a site's search form (see ``run_steps`` for the step
    vocabulary). Steps flagged ``"snapshot": true`` capture the page HTML
    after they run, so paginated results can be collected.

    ``plans`` maps a URL to a *search-form plan*: ``{"candidates": [{"key",
    "require": [css…], "absent": [css…], "steps": […]}, …], "viewport": {…}}``.
    After the page loads, the first candidate whose ``require`` selectors all
    exist (and whose ``absent`` selectors do not) is chosen — that is how
    several versions of one site's form are told apart on the live page — and
    its steps are run; ``Rendered.matched`` names it (``""`` when none matched).
    """
    settings = settings or SearchSettings()
    if not urls:
        return []
    viewport = next((p.get("viewport") for p in (plans or {}).values() if isinstance(p, dict) and p.get("viewport")), None)
    payload = {
        "urls": urls,
        "user_agent": settings.user_agent,
        "timeout_ms": int(settings.timeout_seconds * 1000),
        "delay_seconds": float(delay_seconds),
        "wait_selector": wait_selector,
        "actions": actions or {},
        "plans": plans or {},
        "viewport": viewport,
    }
    steps = sum(len(v) for v in (actions or {}).values())
    steps += sum(max([len(c.get("steps") or []) for c in p.get("candidates", [])] or [0]) for p in (plans or {}).values() if isinstance(p, dict))
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
            matched=r.get("matched", ""),
            initial_html=r.get("initial_html", ""),
        )
        for r in results
    ]


# ---------------------------------------------------------------------------
# Search-form steps
# ---------------------------------------------------------------------------

STEP_KINDS = ("fill", "select", "click", "check", "press", "wait", "scroll", "remember", "wait_change")

# JavaScript fallbacks used by ``"force": true`` when a control is hidden by the responsive layout
# (e.g. a collapsed filter form): the same element is operated through the DOM instead of the mouse.
_JS_FILL = """(el, value) => {
  el.value = value;
  el.dispatchEvent(new Event('input', {bubbles: true}));
  el.dispatchEvent(new Event('change', {bubbles: true}));
}"""
_JS_CHECK = "(el) => { if (!el.checked) { el.click(); } }"
_JS_CLICK = "(el) => { el.click(); }"
_JS_MARK = "(el) => el.innerHTML"


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


def _forced(loc: Any, action: str, value: str, timeout_ms: int, errors: tuple) -> None:
    """Use the real user action when the element is visible; otherwise (hidden by layout) operate it through the DOM."""
    loc.wait_for(state="attached", timeout=timeout_ms)
    if loc.is_visible():
        try:
            quick = min(timeout_ms, 3000)
            if action == "fill":
                loc.fill(value, timeout=quick)
            elif action == "check":
                loc.check(force=True, timeout=quick)  # force: skip the "receives events" wait (custom checkboxes sit under their label)
            else:
                loc.click(force=True, timeout=quick)
            return
        except errors:
            pass
    if action == "fill":
        loc.evaluate(_JS_FILL, value)
    elif action == "check":
        loc.evaluate(_JS_CHECK)
    else:
        loc.evaluate(_JS_CLICK)


def run_steps(page: Any, steps: list[dict[str, Any]], timeout_ms: int) -> tuple[list[str], int, str]:
    """Execute search-form steps on a loaded page. Returns (snapshots, steps_done, error).

    Step kinds: ``fill``, ``select``, ``click``, ``check``, ``press``, ``wait``,
    ``scroll``, ``remember`` (store an element's current content) and
    ``wait_change`` (wait until that element's content differs — for pages that
    pre-render a result list). Modifiers: ``repeat``, ``snapshot``, ``optional``,
    ``timeout_ms``, ``settle_ms`` and ``force`` (operate hidden controls via the DOM).
    """
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import TimeoutError as PlaywrightTimeout

    errors = (PlaywrightTimeout, PlaywrightError)
    snapshots: list[str] = []
    marks: dict[str, str] = {}
    done = 0
    for index, step in enumerate(steps, start=1):
        kind = next((k for k in STEP_KINDS if k in step), None)
        if kind is None:
            return snapshots, done, f"step {index}: unknown step {step!r}"
        repeat = max(1, int(step.get("repeat") or 1))
        step_timeout = int(step.get("timeout_ms") or (min(timeout_ms, 3000) if step.get("optional") and kind not in ("wait", "wait_change") else timeout_ms))
        force = bool(step.get("force"))
        for _ in range(repeat):
            try:
                if kind == "fill":
                    loc = _locator(page, step["fill"])
                    value = str(step.get("value", ""))
                    if force:
                        _forced(loc, "fill", value, step_timeout, errors)
                    else:
                        loc.click(timeout=step_timeout)
                        loc.fill(value, timeout=step_timeout)
                elif kind == "select":
                    loc = _locator(page, step["select"])
                    value = str(step.get("value", ""))
                    try:
                        loc.select_option(label=value, timeout=step_timeout)
                    except PlaywrightError:
                        loc.select_option(value=value, timeout=step_timeout)
                elif kind == "click":
                    loc = _locator(page, step["click"])
                    if force:
                        _forced(loc, "click", "", step_timeout, errors)
                    else:
                        loc.click(timeout=step_timeout)
                elif kind == "check":
                    loc = _locator(page, step["check"])
                    if force:
                        _forced(loc, "check", "", step_timeout, errors)
                    else:
                        loc.check(timeout=step_timeout)
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
                elif kind == "remember":
                    loc = _locator(page, step["remember"])
                    loc.wait_for(state="attached", timeout=step_timeout)
                    marks[json.dumps(step["remember"], sort_keys=True)] = loc.evaluate(_JS_MARK)
                elif kind == "wait_change":
                    key = json.dumps(step["wait_change"], sort_keys=True)
                    before = marks.get(key)
                    loc = _locator(page, step["wait_change"])
                    deadline = time.monotonic() + step_timeout / 1000
                    changed = False
                    while time.monotonic() < deadline:
                        try:
                            current = loc.evaluate(_JS_MARK)
                        except errors:
                            current = None
                        if current is not None and current != before:
                            changed = True
                            break
                        time.sleep(0.25)
                    if not changed:
                        raise PlaywrightTimeout(f"content of {step['wait_change']!r} did not change within {step_timeout} ms")
            except errors as exc:
                if step.get("optional"):
                    break
                return snapshots, done, f"step {index} ({kind} {step.get(kind)!r}) failed: {str(exc).splitlines()[0][:160]}"
            if step.get("snapshot"):
                snapshots.append(page.content())
        done += 1
        if step.get("settle_ms"):
            time.sleep(float(step["settle_ms"]) / 1000)
    return snapshots, done, ""


def pick_candidate(page: Any, candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    """First candidate whose ``require`` selectors all exist on the page and whose ``absent`` selectors do not."""
    for candidate in candidates:
        require = [str(s) for s in candidate.get("require") or []]
        absent = [str(s) for s in candidate.get("absent") or []]
        try:
            if any(page.locator(sel).count() == 0 for sel in require):
                continue
            if any(page.locator(sel).count() > 0 for sel in absent):
                continue
        except Exception:  # noqa: BLE001 - invalid selector
            continue
        return candidate
    return None


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
    plans: dict[str, dict[str, Any]] = payload.get("plans") or {}
    viewport = payload.get("viewport") if isinstance(payload.get("viewport"), dict) else None
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context_args: dict[str, Any] = {"user_agent": payload.get("user_agent") or None, "java_script_enabled": True, "locale": "en-US"}
        if viewport and viewport.get("width") and viewport.get("height"):
            context_args["viewport"] = {"width": int(viewport["width"]), "height": int(viewport["height"])}
        context = browser.new_context(**context_args)
        context.route("**/*", lambda route: route.abort() if route.request.resource_type in ("image", "media", "font") else route.continue_())
        page = context.new_page()
        last = 0.0
        for url in payload.get("urls", []):
            if last and delay:
                pause = delay - (time.monotonic() - last)
                if pause > 0:
                    time.sleep(pause)
            last = time.monotonic()
            row: dict[str, Any] = {
                "url": url, "status": 0, "html": "", "final_url": "", "error": "", "snapshots": [], "steps_done": 0,
                "step_error": "", "matched": "", "initial_html": "",
            }
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
                plan = plans.get(url)
                if plan:
                    row["initial_html"] = page.content()
                    chosen = pick_candidate(page, list(plan.get("candidates") or []))
                    if chosen is None:
                        row["html"] = row["initial_html"]
                        row["final_url"] = page.url
                        results.append(row)
                        continue  # no known version of the form on this page: report it, touch nothing
                    row["matched"] = str(chosen.get("key") or "")
                    steps = list(chosen.get("steps") or [])
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
    if "--setup" in sys.argv[1:]:  # scripts/run_*.sh|bat, Makefile: make sure Playwright + Chromium are present
        ok, reason = ensure_installed(log=print, force=True)
        print("Headless browser ready." if ok else f"Headless browser NOT ready: {reason}")
        return 0 if ok else 1
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
