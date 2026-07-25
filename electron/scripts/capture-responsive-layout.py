"""Capture the built UI at its minimum supported window size with mock data."""

import json
import os
import sys
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else (
    ROOT / "release" / "layout-preview" / "responsive-900x650.png"
)
WIDTH = max(900, int(sys.argv[2])) if len(sys.argv) > 2 else 900
HEIGHT = max(600, int(sys.argv[3])) if len(sys.argv) > 3 else 650


def api_payload(url: str):
    if url.endswith("/health"):
        return {"ok": True}
    if url.endswith("/status"):
        return {
            "api_key_set": True,
            "tavily_set": True,
            "llm_set": True,
            "game_name": "R.E.P.O.",
            "game_root": r"E:\SteamLibrary\steamapps\common\REPO",
            "game_slug": "repo",
            "game_instance_id": "gi_layout_qa",
        }
    if "/games/detect" in url:
        return [{
            "name": "R.E.P.O.",
            "path": r"E:\SteamLibrary\steamapps\common\REPO",
            "slug": "repo",
            "game_instance_id": "gi_layout_qa",
            "source": "steam",
            "adapted": True,
        }]
    if "/chat/tasks/active" in url:
        return {"active": False}
    if "/downloads/status" in url:
        return {"active": []}
    return []


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *_args):
        pass


server = ThreadingHTTPServer(
    ("127.0.0.1", 0),
    partial(QuietHandler, directory=str(ROOT / "dist")),
)
threading.Thread(target=server.serve_forever, daemon=True).start()

with sync_playwright() as playwright:
    launch_options = {"headless": True}
    cached_shells = sorted(
        (Path(os.environ.get("LOCALAPPDATA", "")) / "ms-playwright").glob(
            "chromium_headless_shell-*/chrome-headless-shell-win64/chrome-headless-shell.exe"
        ),
        reverse=True,
    )
    if cached_shells:
        launch_options["executable_path"] = str(cached_shells[0])
    browser = playwright.chromium.launch(**launch_options)
    context = browser.new_context(viewport={"width": WIDTH, "height": HEIGHT})
    page = context.new_page()
    page.add_init_script(
        """
        localStorage.setItem('modagent-layout-mode', 'designed');
        window.modagent = {
          getApiBase: () => 'http://127.0.0.1:18890',
          getBgDataUrl: async () => null,
          getAppIdentity: async () => ({ edition: 'subscription' }),
        };
        """
    )

    def route_api(route):
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(api_payload(route.request.url)),
        )

    page.route("http://127.0.0.1:18890/**", route_api)
    page.goto(f"http://127.0.0.1:{server.server_port}/index.html", wait_until="networkidle")
    page.wait_for_timeout(1200)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(OUTPUT))
    drawer_output = OUTPUT.with_name(f"{OUTPUT.stem}-sessions{OUTPUT.suffix}")
    session_toggle = page.locator('.chat-primary-pane button[title="展开"]')
    if session_toggle.count():
        session_toggle.click()
        page.wait_for_timeout(250)
        page.screenshot(path=str(drawer_output))

    metrics = page.evaluate(
        """
        () => {
          const box = selector => {
            const node = document.querySelector(selector);
            if (!node) return null;
            const rect = node.getBoundingClientRect();
            return {
              x: Math.round(rect.x), y: Math.round(rect.y),
              width: Math.round(rect.width), height: Math.round(rect.height),
              scrollWidth: node.scrollWidth, clientWidth: node.clientWidth,
              scrollHeight: node.scrollHeight, clientHeight: node.clientHeight,
            };
          };
          return {
            viewport: { width: innerWidth, height: innerHeight },
            bodyOverflowX: document.body.scrollWidth > document.body.clientWidth,
            sidebar: box('.app-sidebar'),
            stage: box('.app-page-stage'),
            primary: box('.chat-primary-pane'),
            quick: box('.chat-quick-sidebar'),
            sessions: box('.chat-session-rail'),
          };
        }
        """
    )
    print(json.dumps({
        "capture": str(OUTPUT),
        "drawer_capture": str(drawer_output) if drawer_output.exists() else None,
        "metrics": metrics,
    }, ensure_ascii=False))
    browser.close()

server.shutdown()
