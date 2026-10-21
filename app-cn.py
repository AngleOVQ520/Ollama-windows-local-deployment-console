"""Ollama 控制台 —— 中文启动入口。

运行：python app-cn.py
  --no-browser   不自动打开浏览器
  --port N       临时指定界面端口
  --plain        不使用全屏仪表盘（纯日志输出）
  --lang en      临时改用英文

界面默认中文：浏览器打开后即是中文界面，可在 设置 → 外观 → 界面语言 中切换。
需要英文界面请用 app-en.py 启动（见 app-en.py）。

所有依赖、缓存、日志、数据都保存在本项目文件夹内。
"""
from backend.launcher import run

if __name__ == "__main__":
    run("zh")