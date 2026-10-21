"""界面检查：用系统 Chrome（用户数据目录放在项目 runtime 内）打开各页面，收集控制台错误并截图。
用法：python tests/ui_check.py [base_url]
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "runtime", "devlib"))
sys.path.insert(0, os.path.join(ROOT, "runtime", "pylib"))
os.environ["TEMP"] = os.environ["TMP"] = os.path.join(ROOT, "runtime", "tmp")
os.environ["PLAYWRIGHT_BROWSERS_PATH"] = os.path.join(ROOT, "runtime", "browsers")
from playwright.sync_api import sync_playwright  # noqa: E402

B = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8848"
OUT = os.path.join(ROOT, "runtime", "shots")
os.makedirs(OUT, exist_ok=True)
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"


def launch(p, headless=True):
    return p.chromium.launch_persistent_context(os.path.join(ROOT, "runtime", "chrome-profile"), executable_path=CHROME,
                                                headless=headless, viewport={"width": 1600, "height": 960},
                                                args=["--disable-crash-reporter", "--no-first-run", "--disable-features=Translate"])


if __name__ == "__main__":
    errors = []
    with sync_playwright() as p:
        ctx = launch(p)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.on("console", lambda m: errors.append("[%s] %s" % (m.type, m.text)) if m.type in ("error", "warning") else None)
        page.on("pageerror", lambda e: errors.append("[pageerror] %s" % e))
        for route in ["chat", "add", "models", "stats", "settings"]:
            page.goto(B + "/#/" + route)
            page.wait_for_timeout(1800)
            page.screenshot(path=os.path.join(OUT, "%s.png" % route))
            print("shot", route)
        ctx.close()
    print("console errors:", len(errors))
    for e in errors:
        print("  ", e[:400])
