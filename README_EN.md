[简体中文](README.md) | **English**

# Ollama Console

> Anyone can deploy local models faster — including manually importing GGUF files.
> Use Ollama faster and more conveniently, without learning more command-line flags — truly ready out of the box.
> An all-in-one console for local large language models: chat, partitioned model management, image generation, usage analytics and full parameter tuning — all running on your own machine.
> No online account and no cloud service; dependencies, database, logs and cache all stay inside the project folder.

Two interface languages are supported: **中文** (`app-cn.py`) and **English** (`app-en.py`), switchable at any time in Settings.

---

## Table of Contents

- [Feature Overview](#feature-overview)
- [Requirements](#requirements)
- [Quick Start](#quick-start)
- [Interface Language (中文 / English)](#interface-language-中文--english)
- [Directory Structure](#directory-structure)
- [The Six Main Areas](#the-six-main-areas)
- [Command-line Arguments](#command-line-arguments)
- [HTTP API](#http-api)
- [Data, Storage and Backup](#data-storage-and-backup)
- [Terminal Dashboard](#terminal-dashboard)
- [FAQ](#faq)
- [Development and Testing](#development-and-testing)
- [Design Notes](#design-notes)
- [Version](#version)
- [Contact](#contact)
- [中文快速开始](#中文快速开始)

---

## Feature Overview

| Capability | Description | Status |
| --- | --- | --- |
| Chat | Streaming output, collapsible thinking process, stop at any time, HTML preview / math formulas / Mermaid / code highlighting | Done |
| HTML preview | Choose between "Code" and "Preview"; the preview has mobile / tablet / desktop width switching | Done |
| Model partitions | Any number of partitions; each can point to any folder on any disk, with a custom name | Done |
| Model import | Download from the official Ollama library (runs `ollama run` into the target folder automatically), or import a local GGUF with metadata parsing | Done |
| Model aliases | Each model can have a display alias; lists and pickers prefer the alias | Done |
| MTP speculative decoding | Detects `nextn.* / mtp.*` tensors and `nextn_predict_layers` in the GGUF, and runs supported models in draft-mtp mode automatically | Done |
| Image generation | Text-to-image / image-to-image (stable-diffusion.cpp), with progress, cancel, queue, history and reference images | Done |
| Usage analytics | Today / 7 days / 30 days / all time; by model, by hour, trends, heatmap, distributions, scatter and detail table | Done |
| Public API | Separate port exposing both an OpenAI-compatible interface (`/v1`) and an Ollama native API proxy (`/api`), with API Key, CORS and LAN support | Done |
| Terminal dashboard | Boot animation + live dashboard (system / current model / engines / usage & jobs / live log) | Done |
| Interface language | Chinese / English, with the default decided by the entry point and switchable in Settings | Done |
| Data backup | Automatic backup on start, manual backup / restore, settings import & export | Done |
| Local-first | Dependencies, cache, logs, database and models all stay inside the project folder; nothing is uploaded | Done |

---

## Requirements

| Item | Requirement |
| --- | --- |
| OS | Windows 10 / 11 (currently implemented for Windows, including a one-time environment sandboxing) |
| Python | 3.10 or newer (this project runs on 3.12 / 3.13) |
| Ollama | Must be installed locally (verified with v0.40.4 or newer) |
| GPU | Optional. NVIDIA availability is probed via `nvidia-ml-py`; falls back to CPU inference when there is no discrete GPU |
| Disk | Reserve enough space for GGUF / image-generation models (a single model can range from several GB to dozens of GB) |

There are only 5 Python dependencies (see `requirements.txt`):

```
flask==3.1.3
requests==2.34.2
rich==15.0.0
psutil==7.2.2
nvidia-ml-py==13.615.71
```

**On first run they are installed into `runtime/pylib` automatically, so your system Python is never touched.**

---

## Quick Start

1. Make sure Ollama is installed locally (`ollama --version` should print normally).
2. In the project root, run:

```powershell
# Chinese UI (default)
python app-cn.py

# English UI
python app-en.py

# Do not open the browser automatically (server / remote desktop)
python APP-NO.py

# Temporary port, plain log mode
python app-cn.py --port 9000 --plain
```

3. The browser opens `http://127.0.0.1:8848` automatically (the port can be changed in Settings → Interface service).
4. In "Add model", create a partition and download / import a model, then go back to "Home" and pick a model in the bottom-left of the input box to start chatting.

> On first launch an ~8-second terminal boot animation plays (it can be set to "Fast / Off" in Settings → Appearance → Terminal boot animation).

---

## Interface Language (中文 / English)

The language is determined by both the **entry point** and the **setting**, as follows:

| `ui.language` setting | Actual language |
| --- | --- |
| `Follow launcher` (default) | Determined by the entry point: `app-cn.py` → Chinese, `app-en.py` → English |
| `中文` | Always Chinese |
| `English` | Always English |

- The terminal boot animation and live dashboard **always follow the entry point** (`app-cn.py` / `app-en.py`, or a temporary override via `--lang`).
- The browser UI can be switched at any time under **Settings → Appearance → Interface language**; the change takes effect immediately without a restart.
- **Backend-generated text** (run logs, API error messages, model loading stage names, job messages, Markdown export body) follows the **interface language**:
  the front end attaches an `X-Lang` request header to every request (`?lang=` for event streams) and the backend returns text in the matching language.
  So even if the entry point started in English, switching the UI back to Chinese makes error messages and logs Chinese as well, and vice versa.
- When started with `app-en.py`, the server injects the language into the page, so the very first frame is English with no flash of Chinese.

---

## Directory Structure

```
ollama最终兵器/
├── app-cn.py              # Chinese entry point
├── app-en.py              # English entry point
├── APP-NO.py              # Entry point that does not auto-open the browser
├── requirements.txt
├── backend/
│   ├── launcher.py        # Startup flow (environment sandboxing + service orchestration + boot animation)
│   ├── i18n.py            # Terminal / server-side Chinese & English text
│   ├── console.py         # Boot animation + live dashboard (rich)
│   ├── context.py         # Application context assembly
│   ├── core/              # Config, database, GGUF parsing, Ollama client, event bus
│   ├── routes/            # Flask blueprints (chat / models / stats / image gen / misc)
│   ├── services/          # Engines, loader, chat, image gen, jobs, registry, usage, system monitor
│   └── priv/              # Privilege-related (Shizuku / accessibility and other optional capabilities)
├── web/                   # Front end (vanilla ES modules, no build step)
│   ├── index.html
│   └── static/
│       ├── css/           # Tokens, shell, chat, pages, image gen
│       ├── js/core/       # API, state, UI utilities, icons, Markdown, i18n engine
│       ├── js/pages/      # The six page modules
│       ├── js/i18n/       # English word lists (split by module)
│       └── vendor/        # Locally bundled third-party libs (ECharts / KaTeX / highlight.js / mermaid / DOMPurify)
├── data/                  # Database, settings mirror, generated images, backups
├── runtime/               # Dependencies, logs, temp files, Ollama runtime dir, sd executables
└── tests/                 # End-to-end and UI test scripts
```

---

## The Six Main Areas

### 1. Home (Chat)

- In the input area, from left to right: **model picker** → attachments → context → parameters → thinking → send / stop.
- Selecting a model **starts loading immediately**, with a live progress bar below the button; switching models while loading unloads the old one first, and switching during a conversation waits until output finishes or is stopped manually before reloading.
- Deep thinking has 8 levels: `Off / MINI / LOW / MEDIUM / HIGH / X-HIGH / MAX / ULTRA`, each with a configurable thinking-token budget (0 means unlimited).
- After the model finishes, a stats line is appended: input tokens, output tokens, generation speed, inference time and time to first token.
- The history list on the left supports collapsing, search, pinning, renaming, deleting and clearing.
- Supports pasting / dropping images and text files; HTML can be toggled between "Code / Preview", and math formulas, Mermaid and code highlighting are all rendered locally.

### 2. Add Model

- Partition management: a partition can point to any folder on any disk, with a custom name, and partitions do not affect each other.
- Two import methods: download from the official Ollama library (enter the model ID and it runs `ollama run …` into the target folder), or import a local GGUF directly.
- GGUF metadata is parsed before import: architecture, parameter count, quantization type, max context, MTP head, etc.
- A job queue at the bottom shows download / import progress and stages.

### 3. Model List

Table columns: alias, model ID, category, added time, parameter count, model size, max context, (MTP flag).
Supports filtering by partition, keyword search, in-place editing of the alias by clicking it, viewing model details (metadata / default parameters / template / license / notes) and deletion.

### 4. Image Generation

- Based on stable-diffusion.cpp: text-to-image and image-to-image, with the full set of width / height / steps / CFG / sampler / scheduler / seed / batch parameters, plus a collapsible "Advanced parameters" area.
- Live progress (steps, per-step time, ETA, queue), cancellable at any time.
- History entries can be previewed, downloaded and cleared; retention days and automatic cleanup are supported.

### 5. Usage Analytics

- Ranges: Today / 7 days / 30 days / All time.
- Charts: usage trend (stacked input / output / thinking), model ranking, hourly heatmap, source and status distributions, speed-vs-duration scatter.
- Detail table: per model and per call, including failure counts and time to first token.
- Every chat and API call (`source=api`) is recorded; recording can be turned off in Settings → API service.

### 6. Settings

14 sections: Appearance, Chat, Deep thinking, Default parameters, Context, Ollama engine, Image generation, API service, Interface service, Prompt presets, Data & backup, Run logs, Shortcuts, About.

- **Appearance**: theme (dark / light / follow system), interface language, accent color, font size, message area width, interface animations, terminal boot animation, animation speed, history sidebar.
- **Engine**: Ollama path, starting port, keep-alive, Flash Attention, KV cache precision, parallelism, load timeout, speculative decoding type, etc.
- **API service**: on/off, port, LAN listening, API Key, CORS, whether to count toward usage.
- **Prompt presets**: built-in general assistant / coding expert / translator / front-end designer / math teacher, etc., freely editable.

---

## Command-line Arguments

All entry points share the same set of arguments (defined in `backend/launcher.py`):

| Argument | Description |
| --- | --- |
| `--no-browser` | Do not open the browser automatically after starting |
| `--port N` | Temporarily override the UI port (default from settings, 8848) |
| `--plain` | Plain log output, no full-screen dashboard |
| `--lang zh\|en` | Temporarily override the language for this run (terminal and browser default language) |

---

## HTTP API

Exposed to the LAN / local machine, default port `8849` (changeable or disableable in Settings).

- `GET /` — service description
- `GET /v1/models`, `POST /v1/chat/completions` — OpenAI-compatible
- `/api/*` — Ollama native API proxy
- A model name may be written as `model ID` or `partition name/model ID`
- Supports Bearer Key authentication, CORS and LAN listening

---

## Data, Storage and Backup

| Path | Contents |
| --- | --- |
| `data/app.db` | **Single source of truth**: settings, chats, model registry, usage, jobs (SQLite + WAL) |
| `data/settings.json` | Readable mirror of settings, for inspection and manual backup (the database is still the source of truth) |
| `data/images/` | Generated images (stored per job ID, including previews) |
| `data/backups/auto-*/` | Automatic backups taken at startup |
| `runtime/pylib/` | Project-local Python dependencies |
| `runtime/logs/` | Run logs (including `errors.log`) |
| `runtime/home/.ollama/` | Project-isolated Ollama runtime directory |
| `runtime/sdcpp/` | stable-diffusion.cpp executables and CUDA runtime libraries |

Everything lives inside the project folder — deleting the whole directory completes a full cleanup (if a model directory points to an external disk, clean that separately).

---

## Terminal Dashboard

At startup a multi-stage animation plays: kernel boot → logo reveal → version badge → system check → hardware scan → charge-up → READY burst, then seamlessly switches to the live dashboard:

- **System**: CPU / memory / GPU / VRAM (including GPU model and temperature)
- **Current model**: status, progress, stage, context, VRAM usage, load time
- **Engines**: engine port and status for each partition, API service address
- **Usage & jobs**: today / cumulative usage, average speed, first token, jobs in progress
- **Live log**: scrolling log, exit with `Ctrl+C` (closing the browser does not affect the background process)

Terminals that do not support the full-screen animation (dumb terminals / pipes / small windows / `--plain`) automatically fall back to a line-by-line concise mode.

---

## FAQ

**Q: What if the port is already in use?**
At startup the app automatically looks for the next free port after the preferred one; you can also specify one with `--port N`, or change it in Settings → Interface service.

**Q: The UI will not open / shows a blank page?**
Check that the terminal window is still running (closing it terminates the background process); also make sure nothing — such as antivirus — is blocking the port listener.

**Q: The model list does not show a model I just downloaded?**
Click "Rescan" in the "Model list"; if the model is in a custom partition, verify the partition path.

**Q: What does "MTP —" mean?**
It means the GGUF has no `nextn.* / mtp.*` tensors or `nextn_predict_layers` declaration, so the engine cannot enable speculative decoding — this is a limitation of the file itself, and the flag is accurate.

**Q: How do I fully reset?**
The settings page has "Restore all defaults"; at the data level, deleting `data/app.db` clears chats / usage / model registry (back up first).

**Q: Can I run multiple instances?**
Yes, but they need different UI ports, API ports and engine starting ports, and sharing the same data directory will cause them to overwrite each other — copying the project folder is recommended.

---

## Development and Testing

`tests/` contains real test scripts; most require `app-cn.py` to be running first:

| Script | Purpose |
| --- | --- |
| `smoke_api.py` | Backend API smoke test |
| `regression.py` | Main flow regression |
| `ui_flow.py` | UI interaction (floating window, model switching, send / stop, HTML preview, formulas) |
| `console_pty.py` / `console_dumb.py` | Terminal UI and fallback paths |
| `launch_real.py` | Launch the real way and self-check |
| `mtp_*.py` | A/B and end-to-end verification of MTP speculative decoding |
| `settings_persist.py` | Settings persistence |
| `e2e_image.py` / `probe_*.py` | Image-generation pipeline |

The front end is **vanilla ES modules with no build step** — just refresh after editing (static assets are strictly non-cached).

---

## Design Notes

- **Interface**: dark-first, avoiding blue-purple / gold; the top navigation uses a hand-drawn liquid-glass slider (spring driven, velocity deformation, edge refraction highlight), and the model / context / parameters / thinking buttons in the input area use 3D skeuomorphism + elastic press.
- **Bilingual implementation (front end)**: the source is always written in Chinese; in English mode a runtime i18n layer replaces text and tooltip attributes at the DOM level, with word lists in `web/static/js/i18n/`. Chinese mode has zero overhead, can be switched back at any time, and translation changes never break existing interaction logic.
- **Bilingual implementation (back end)**: also keyed by the Chinese source text; `backend/i18n.py` provides `T()`, and word lists are split under `backend/i18n_parts/*.py` per module. Terminal text uses the startup language; HTTP request text is decided by `X-Lang`, keeping it consistent with the browser UI.
- **Language-independent content**: partition names, model aliases, disk paths, chat titles, custom prompt presets, GGUF field values and other user data remain unchanged in any language.
- **Configuration**: SQLite is the single source of truth and `settings.json` is only a mirror, preventing manual edits from diverging from the program state.

---

## Version

`v1.0.0` · Backend API version in `backend/__init__.py`

---

## Contact

- **Email**: dvdvjvb@163.com

Questions, suggestions or bug reports are welcome by email.

---

## 中文快速开始

**Ollama 控制台** —— 面向 Ollama 的本地优先控制中心：对话、分区式模型管理、生图、用量统计与全参数调优。

### 环境要求

Windows 10/11、Python 3.10+，以及本机安装的 Ollama。NVIDIA 显卡可选（也可用 CPU 推理）。

### 运行

```powershell
python app-cn.py                 # 中文界面与中文命令行仪表盘
python app-cn.py --port 9000     # 自定义界面端口
python app-cn.py --no-browser    # 不自动打开浏览器
python APP-NO.py --lang zh       # 同上，但不自动打开浏览器
```

浏览器会自动打开 `http://127.0.0.1:8848`（默认端口）。首次运行时依赖会安装到 `runtime/pylib`，不会污染系统 Python。

### 语言

`app-cn.py` 会让命令行仪表盘与网页界面都以中文启动。界面语言也可以在运行时于 **设置 → 外观 → 界面语言** 中切换，共有三个选项：

- **跟随启动器** —— 使用启动入口对应的语言（`app-cn.py` → 中文，`app-en.py` → 英文）
- **中文** —— 始终中文
- **English** —— 始终英文

命令行仪表盘的语言始终跟随启动入口（或 `--lang`），与浏览器界面相互独立。

### 数据

所有内容都位于项目文件夹内：`data/app.db`（SQLite，唯一真源）、`data/settings.json`（可读镜像）、`data/images/`（生图产物）、`data/backups/`（自动备份）、`runtime/`（依赖、日志、临时文件）。不会上传到任何地方。

### 联系方式

邮箱：**dvdvjvb@163.com**