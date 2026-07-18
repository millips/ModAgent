"""Optional Playwright enhancement layer for ModAgent's existing Chrome.

The application still owns and launches Chrome.  Playwright attaches over CDP
to add ARIA snapshots, auto-waiting actions, dialog state, and download events.
Every public function fails softly so the caller can fall back to raw CDP.
"""

from __future__ import annotations

import os
import re
import time
from pathlib import Path
from typing import Optional

from .config import CONFIG_DIR


DOWNLOAD_DIR = Path(CONFIG_DIR) / "browser-downloads"
_DANGER_RE = re.compile(
    r"delete|remove|purchase|buy now|subscribe|unsubscribe|upload|publish|"
    r"post|send message|删除|购买|订阅|退订|上传|发布",
    re.I,
)


def available() -> bool:
    try:
        import playwright.sync_api  # noqa: F401
        return True
    except Exception:
        return False


def _connect(cdp_port: int):
    from playwright.sync_api import sync_playwright

    runtime = sync_playwright().start()
    try:
        browser = runtime.chromium.connect_over_cdp(
            f"http://127.0.0.1:{int(cdp_port)}",
            timeout=5000,
            is_local=True,
            no_defaults=True,
            artifacts_dir=str(DOWNLOAD_DIR),
        )
        return runtime, browser
    except Exception:
        runtime.stop()
        raise


def _find_page(browser, url: str, title: str = ""):
    pages = [
        page
        for context in browser.contexts
        for page in context.pages
    ]
    exact = next((page for page in pages if page.url == url), None)
    if exact:
        return exact
    same_base = next((
        page for page in pages
        if page.url.split("#", 1)[0] == str(url).split("#", 1)[0]
    ), None)
    if same_base:
        return same_base
    if title:
        for page in pages:
            try:
                if page.title() == title:
                    return page
            except Exception:
                continue
    return None


def doctor(cdp_port: int) -> dict:
    result = {
        "driver": "playwright",
        "library_available": available(),
        "connected": False,
        "contexts": 0,
        "pages": 0,
    }
    if not result["library_available"]:
        result["error"] = "Playwright library unavailable; using CDP fallback"
        return result
    runtime = browser = None
    started = time.monotonic()
    try:
        runtime, browser = _connect(cdp_port)
        result.update(
            connected=True,
            contexts=len(browser.contexts),
            pages=sum(len(context.pages) for context in browser.contexts),
            latency_ms=round((time.monotonic() - started) * 1000),
        )
    except Exception as exc:
        result["error"] = str(exc)
    finally:
        if runtime:
            runtime.stop()
    return result


def aria_snapshot(cdp_port: int, url: str, title: str = "") -> dict:
    if not available():
        return {"status": "unavailable"}
    runtime = browser = None
    try:
        runtime, browser = _connect(cdp_port)
        page = _find_page(browser, url, title)
        if not page:
            return {"status": "page_not_found"}
        page.set_default_timeout(5000)
        snapshot = page.aria_snapshot(
            mode="default", depth=14, boxes=False, timeout=5000
        )
        return {
            "status": "ok",
            "driver": "playwright",
            "aria_snapshot": snapshot[:24000],
        }
    except Exception as exc:
        return {"status": "failed", "error": str(exc)}
    finally:
        if runtime:
            runtime.stop()


def click(
    cdp_port: int, url: str, target_id: str, title: str = "",
) -> dict:
    """Click a target with Playwright auto-waiting and capture downloads."""
    if not available():
        return {"status": "unavailable"}
    runtime = browser = None
    downloads: list[dict] = []
    try:
        runtime, browser = _connect(cdp_port)
        page = _find_page(browser, url, title)
        if not page:
            return {"status": "page_not_found"}
        page.set_default_timeout(10000)
        DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

        def on_download(download):
            suggested = re.sub(
                r'[<>:"/\\|?*\x00-\x1f]', "_",
                download.suggested_filename or "download.bin",
            )
            stem, suffix = os.path.splitext(suggested)
            target = DOWNLOAD_DIR / suggested
            counter = 2
            while target.exists():
                target = DOWNLOAD_DIR / f"{stem}_{counter}{suffix}"
                counter += 1
            download.save_as(target)
            downloads.append({
                "url": download.url,
                "suggested_filename": download.suggested_filename,
                "local_path": str(target.resolve()),
                "failure": download.failure(),
            })

        page.on("download", on_download)
        locator = page.locator(
            f'[data-modagent-target="{target_id}"]'
        )
        if locator.count() != 1:
            return {
                "status": "target_missing" if locator.count() == 0 else "target_ambiguous",
                "target_id": target_id,
                "matches": locator.count(),
            }
        label = locator.evaluate(
            "(el) => String(el.innerText || el.value || "
            "el.getAttribute('aria-label') || '').trim()"
        )
        if _DANGER_RE.search(label or ""):
            return {
                "status": "dangerous_action_blocked",
                "target_id": target_id,
                "label": label,
            }
        locator.click(timeout=10000)
        page.wait_for_timeout(900)
        return {
            "status": "clicked",
            "driver": "playwright",
            "downloads": downloads,
            "url": page.url,
        }
    except Exception as exc:
        return {"status": "failed", "error": str(exc)}
    finally:
        if runtime:
            runtime.stop()


def input_text(
    cdp_port: int, url: str, target_id: str, value: str, *,
    title: str = "", submit: bool = False,
) -> dict:
    if not available():
        return {"status": "unavailable"}
    runtime = None
    try:
        runtime, browser = _connect(cdp_port)
        page = _find_page(browser, url, title)
        if not page:
            return {"status": "page_not_found"}
        page.set_default_timeout(10000)
        locator = page.locator(f'[data-modagent-target="{target_id}"]')
        count = locator.count()
        if count != 1:
            return {
                "status": "target_missing" if count == 0 else "target_ambiguous",
                "target_id": target_id,
                "matches": count,
            }
        field = locator.evaluate(
            "(el) => ({type:String(el.type||'').toLowerCase(),"
            "autocomplete:String(el.autocomplete||'').toLowerCase()})"
        )
        if field.get("type") == "password" or re.search(
            r"password|cc-|one-time-code", field.get("autocomplete", "")
        ):
            return {"status": "sensitive_input_blocked", "target_id": target_id}
        locator.fill(str(value))
        if submit:
            locator.press("Enter")
        return {
            "status": "input_set",
            "driver": "playwright",
            "target_id": target_id,
            "submitted": submit,
            "url": page.url,
        }
    except Exception as exc:
        return {"status": "failed", "error": str(exc)}
    finally:
        if runtime:
            runtime.stop()


def wait_for(
    cdp_port: int, url: str, *,
    text: str = "", url_pattern: str = "", timeout_ms: int = 10000,
) -> dict:
    if not available():
        return {"status": "unavailable"}
    runtime = browser = None
    timeout_ms = max(200, min(int(timeout_ms), 30000))
    try:
        runtime, browser = _connect(cdp_port)
        page = _find_page(browser, url)
        if not page:
            return {"status": "page_not_found"}
        if text:
            page.get_by_text(text, exact=False).first.wait_for(
                state="visible", timeout=timeout_ms
            )
            condition = {"text": text}
        elif url_pattern:
            page.wait_for_url(url_pattern, timeout=timeout_ms)
            condition = {"url_pattern": url_pattern}
        else:
            page.wait_for_load_state("domcontentloaded", timeout=timeout_ms)
            condition = {"load_state": "domcontentloaded"}
        return {
            "status": "condition_met",
            "driver": "playwright",
            "condition": condition,
            "url": page.url,
        }
    except Exception as exc:
        return {"status": "timeout_or_failed", "error": str(exc)}
    finally:
        if runtime:
            runtime.stop()
