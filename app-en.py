"""Ollama Console —— English launcher.

Run: python app-en.py
  --no-browser   do not open the browser automatically
  --port N       override the UI port
  --plain        plain log output, no dashboard
  --lang zh      switch back to Chinese for this run

The browser opens in English by default; you can still change it under
Settings → Appearance → Interface language.

Dependencies, cache, logs and data all stay inside this project folder.
（本文件同样支持中文说明：用 app-en.py 启动时，浏览器与命令行均为英文。）
"""
from backend.launcher import run

if __name__ == "__main__":
    run("en")