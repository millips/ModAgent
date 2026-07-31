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
        # Nexus free downloads begin after a visible three-second countdown.
        # Keep the listener alive until the delayed browser event arrives.
        wait_ms = 6500 if re.search(r"slow\s*download", label or "", re.I) else 1200
        page.wait_for_timeout(wait_ms)
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


def click_download_control(
    cdp_port: int, url: str, stage: str, capture_dir: str, file_id: int = 0,
) -> dict:
    """Fallback for Nexus controls that reject or lose raw CDP mouse events.

    Unlike the general browser tool this helper stays inside the downloader,
    keeps a download listener alive through Nexus' free-account countdown and
    writes the captured file into the downloader's own staging directory.
    """
    if not available():
        return {"status": "unavailable", "clicked": False}
    runtime = browser = None
    downloads: list[str] = []
    try:
        runtime, browser = _connect(cdp_port)
        page = _find_page(browser, url)
        if not page:
            # A Manual click can rewrite the query string. Match the stable mod
            # page portion before giving up.
            marker = str(url).split("?", 1)[0]
            page = next((
                candidate
                for context in browser.contexts for candidate in context.pages
                if candidate.url.split("?", 1)[0] == marker
            ), None)
        if not page:
            return {"status": "page_not_found", "clicked": False}
        page.set_default_timeout(8000)
        Path(capture_dir).mkdir(parents=True, exist_ok=True)

        def on_download(download):
            suggested = re.sub(
                r'[<>:"/\\|?*\x00-\x1f]', "_",
                download.suggested_filename or "nexus-download.bin",
            )
            target = Path(capture_dir) / suggested
            stem, suffix = target.stem, target.suffix
            counter = 2
            while target.exists():
                target = Path(capture_dir) / f"{stem}_{counter}{suffix}"
                counter += 1
            download.save_as(target)
            downloads.append(str(target.resolve()))

        page.on("download", on_download)
        labels = {
            "slow": re.compile(r"^\s*slow\s*download\s*$", re.I),
            "manual": re.compile(r"^\s*manual(?:\s+download)?\s*$", re.I),
            "intermediate": re.compile(r"^\s*(?:continue|download|download anyway|next)\s*$", re.I),
            "files": re.compile(r"^\s*files(?:\s+\d+)?\s*$", re.I),
        }
        pattern = labels.get(stage)
        if not pattern:
            return {"status": "unsupported_stage", "clicked": False}
        locator = page.get_by_text(pattern, exact=True)
        component_scoped = False
        if stage == "manual" and int(file_id or 0) > 0:
            component = page.locator(
                f'mod-file-download[file-id="{int(file_id)}"]'
            )
            if component.count() == 1:
                exact_locator = component.get_by_text(pattern, exact=True)
                if exact_locator.count():
                    locator = exact_locator
                    component_scoped = True
        visible = []
        for index in range(min(locator.count(), 12)):
            item = locator.nth(index)
            try:
                if item.is_visible() and item.is_enabled():
                    visible.append(item)
            except Exception:
                continue
        if not visible:
            return {"status": "target_missing", "clicked": False}
        if stage == "manual" and len(visible) > 1:
            # A multi-file Nexus page can contain one Manual button per
            # variant.  Clicking the first one would silently install a
            # different file than the user selected.
            if not component_scoped:
                return {
                    "status": "target_ambiguous",
                    "clicked": False,
                    "file_id": int(file_id or 0),
                    "matches": len(visible),
                }
        target = visible[0]
        target.scroll_into_view_if_needed()
        target.click(timeout=8000)
        # Slow download has a visible countdown before the browser event.
        page.wait_for_timeout(8500 if stage == "slow" else 1800)
        return {
            "status": "clicked", "clicked": True,
            "downloads": downloads, "url": page.url,
        }
    except Exception as exc:
        return {"status": "failed", "clicked": False, "error": str(exc)[:300]}
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
