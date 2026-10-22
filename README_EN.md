**Simplified Chinese** | [English](README_EN.md)

# Ollama Console

![Ollama Console UI preview](screenshots/中文.png)

> Let everyone deploy local models faster (including manual GGUF import).
> Truly out-of-the-box, with almost zero learning cost and no need to configure complicated parameters—just finish reading this README.md,!
> and you can start using models that are truly deployed on your local machine! And complete any task (depending on your model).

Two supported UI languages: **Chinese** (`app-cn.py`) and **English** (`app-en.py`), switchable at any time in Settings.
Start directly - [Quick Start](#快速开始)

---

## Table of Contents

- [Feature Overview](#特性总览)
- [Environment Requirements](#环境要求)
- [Quick Start](#快速开始)
- [UI Language (Chinese / English)](#界面语言中文--english)
- [Directory Structure](#目录结构)
- [The Six Main Areas](#六大功能区)
- [CLI Arguments](#命令行参数)
- [HTTP API](#http-api)
- [Data, Storage & Backup](#数据存储与备份)
- [CLI Dashboard](#命令行仪表盘)
- [FAQ](#常见问题)
- [Development & Testing](#开发与测试)
- [Design Notes](#设计说明)
- [Version](#版本)
- [Contact](#联系方式)
- [English Quick Start](#english-quick-start)

---

## Feature Overview

| Capability | Description | Status |
| --- | --- | --- |
| Chat | Streaming output, collapsible thinking process display, stop at any time, HTML preview / math formulas / Mermaid / code highlighting | Implemented |
| HTML preview | Choose "Code" or "Preview"; preview includes mobile / tablet / desktop width switching | Implemented |
| Model partitions | Any number of partitions; each partition can point to any folder on any disk, with a customizable partition name | Implemented |
| Model import | Download from the official Ollama library (automatically runs `ollama run` into the specified directory), or directly import a local GGUF and parse its metadata | Implemented |
| Model notes | A note name can be written for each model; lists and selectors show the note first | Implemented |
| MTP speculative decoding | Detects `nextn.* / mtp.*` tensors and `nextn_predict_layers` in GGUF, and automatically runs supported models in draft-mtp mode | Implemented |
| Image generation | Text-to-image / image-to-image (stable-diffusion.cpp), progress, cancel, queue, history, and reference images | Implemented |
| Usage statistics | Day / 7 days / 30 days / all; by model, by hour, trend, heatmap, distribution, scatter, and detail table | Implemented |
| External API | Independent port, providing both OpenAI-compatible endpoints (`/v1`) and an Ollama native API proxy (`/api`), supporting API Key, CORS, and LAN | Implemented |
| CLI dashboard | Startup animation + real-time dashboard (system / current model / engine / usage & tasks / live logs) | Implemented |
| UI language | Chinese / English bilingual; the default is determined by the startup entry, and it can also be switched in Settings | Implemented |
| Data backup | Automatic backup on startup, manual backup / restore, settings import & export | Implemented |
| Local-first | Dependencies, cache, logs, database, and models all stay inside the project directory; no data is uploaded | Implemented |

---

## Environment Requirements

| Item | Requirement |
| --- | --- |
| Operating system | Windows 10 / 11 (currently implemented for Windows, including one-time environment sandboxing) |
| Python | 3.10 or higher (this project runs on 3.12 / 3.13) |
| Ollama | Must be installed locally (tested with v0.40.4 or newer) |
| GPU | Optional. NVIDIA GPU availability is detected via `nvidia-ml-py`; without a discrete GPU it automatically falls back to CPU inference |
| Disk | It is recommended to reserve enough space for GGUF / image-generation models (a single model can be several GB to tens of GB) |

There are only 5 Python dependencies (see `requirements.txt`):

```
flask==3.1.3
requests==2.34.2
rich==15.0.0
psutil==7.2.2
nvidia-ml-py==13.615.71
```

**On first run, these dependencies are automatically installed into `runtime/pylib`, without polluting the system Python.**

---

## Quick Start

1. Make sure Ollama is installed locally (`ollama --version` outputs normally).
2. In the project root directory, run:

```powershell
# Chinese UI (default)
python app-cn.py

# English UI
python app-en.py

# Do not open the browser automatically (server / remote desktop scenarios)
python APP-NO.py

# Temporarily change the port, plain log mode
python app-cn.py --port 9000 --plain
```

3. The browser automatically opens `http://127.0.0.1:8848` (the port can be changed in Settings → Interface Service).
4. In "Add Model", create a partition and download / import a model; then go back to "Home" and select the model at the bottom-left of the input box to start chatting.

> On first startup, an approximately 8-second CLI startup animation plays (it can be changed to "Fast / Off" in Settings → Appearance → CLI boot animation).

---

## UI Language (Chinese / English)

The language is determined jointly by the **startup entry** and the **settings item**, with the following rules:

| `ui.language` setting | Actual language |
| --- | --- |
| `Follow launcher` (default) | Determined by the startup entry: `app-cn.py` → Chinese, `app-en.py` → English |
| `Chinese` | Always Chinese |
| `English` | Always English |

- The language of the CLI startup animation and real-time dashboard **always follows the startup entry** (`app-cn.py` / `app-en.py`; it can also be temporarily overridden with `--lang`).
- The browser UI can be switched at any time in **Settings → Appearance → UI Language**; the switch takes effect immediately without a restart.
- **Backend-generated text** (runtime logs, API error messages, model loading stage names, task messages, Markdown export body) follows the **UI language**:
  the frontend sends an `X-Lang` request header on every request (event streams use `?lang=`), and the backend returns text in the corresponding language accordingly.
  Therefore, even if the startup entry is English, after switching the UI back to Chinese, error messages and logs will also be in Chinese, and vice versa.
- When started with `app-en.py`, the server injects the language into the page, so the first frame is already English and does not briefly flash Chinese.

---

## Directory Structure

```
ollama-final-weapon/
├── app-cn.py              # Chinese startup entry
├── app-en.py              # English startup entry
├── APP-NO.py              # Startup entry that does not open the browser automatically
├── requirements.txt
├── backend/
│   ├── launcher.py        # Startup flow (environment sandboxing + service orchestration + startup animation)
│   ├── i18n.py            # CLI / server-side Chinese & English strings
│   ├── console.py         # Startup animation + real-time dashboard (rich)
│   ├── context.py         # Application context assembly
│   ├── core/              # Config, database, GGUF parsing, Ollama client, event bus
│   ├── routes/            # Flask blueprints (chat / models / statistics / image generation / misc)
│   ├── services/          # Engine, loader, chat, image generation, tasks, registry, usage, system monitoring
│   └── priv/              # Privilege escalation related (optional capabilities such as Shizuku / accessibility)
├── web/                   # Frontend (native ES modules with no build step)
│   ├── index.html
│   └── static/
│       ├── css/           # Tokens, shell, chat, pages, image generation
│       ├── js/core/       # API, state, UI utilities, icons, Markdown, i18n engine
│       ├── js/pages/      # Six page modules
│       ├── js/i18n/       # English word lists (split by module)
│       └── vendor/        # Localized third-party libraries (ECharts / KaTeX / highlight.js / mermaid / DOMPurify)
├── data/                  # Database, settings mirror, image generation artifacts, backups
├── runtime/               # Dependencies, logs, temporary files, Ollama runtime directory, sd executables
└── tests/                 # End-to-end and UI live-test scripts
```

---

## The Six Main Areas

### 1. Home (Chat)

- The input box area, from left to right: **Select model** → Attachments → Context → Parameters → Thinking → Send / Stop.
- After selecting a model, **loading starts immediately**, with a real-time progress bar below the button; switching models while loading unloads first and then loads the new model; switching models during a conversation waits for the output to finish or for a manual stop before reloading.
- Deep thinking supports 8 levels: `Off / MINI / LOW / MEDIUM / HIGH / X-HIGH / MAX / ULTRA`; each level can set a thinking token budget (0 means unlimited).
- After the model output ends, a statistics line is appended: input tokens, output tokens, generation speed, inference time, and time to first token.
- The history list on the left supports collapsing, searching, pinning, renaming, deleting, and clearing.
- Supports pasting / dragging in images and text files; HTML can toggle between "Code / Preview", and math formulas, Mermaid, and code highlighting are all rendered locally.

### 2. Add Model

- Partition management: partitions can point to any folder on any disk, with custom names, and do not affect each other.
- Two import methods: download from the official Ollama library (enter the model ID, and `ollama run …` is automatically executed into the target directory), or directly import a local GGUF.
- Before import, GGUF metadata is parsed: architecture, parameter count, quantization type, maximum context, MTP header, etc.
- A task queue is provided at the bottom to view download / import progress and stages.

### 3. Model List

Table columns: note name, model ID, category, added time, parameter count, model size, maximum context, (MTP marker).
Supports filtering by partition, searching by keyword, instant editing by clicking the note, viewing model details (metadata / default parameters / template / license / notes), and deletion.

### 4. Image Generation

- Based on stable-diffusion.cpp: text-to-image and image-to-image, with adjustable width / height / steps / CFG / sampler / scheduler / seed / batch and a full set of parameters, plus a collapsible "Advanced Parameters" area.
- Real-time progress (steps, time per step, remaining time, queue), cancellable at any time.
- History records can be previewed, downloaded, and cleared; retention days and automatic cleanup are supported.

### 5. Usage Statistics

- Range: today / 7 days / 30 days / all.
- Charts: usage trend (stacked input / output / thinking), model ranking, hourly heatmap, source and status distribution, speed-vs-time scatter.
- Detail table: by model, by individual call, including failure count and time to first token.
- All conversations and API calls (`source=api`) are counted; recording can be turned off in Settings → API Service.

### 6. Settings

14 sections: Appearance, Chat, Deep Thinking, Default Parameters, Context, Ollama Engine, Image Generation, API Service, Interface Service, Prompt Presets, Data & Backup, Runtime Logs, Shortcuts, About.

- **Appearance**: theme (dark / light / follow system), UI language, accent color, font size, message area width, UI animations, CLI boot animation, animation speed, history sidebar.
- **Engine**: Ollama path, starting port, keep-alive, Flash Attention, KV Cache precision, parallelism, load timeout, speculative decoding type, etc.
- **API Service**: switch, port, LAN listening, API Key, CORS, whether to count towards usage.
- **Prompt Presets**: built-in general assistant / code expert / translator / frontend designer / math teacher, etc., which can be added, deleted, and modified freely.

---

## CLI Arguments

All entries share the same set of arguments (defined in `backend/launcher.py`):

| Argument | Description |
| --- | --- |
| `--no-browser` | Do not open the browser automatically after startup |
| `--port N` | Temporarily specify the UI port (defaults to the value from settings, 8848) |
| `--plain` | Plain log output; does not enter the fullscreen dashboard |
| `--lang zh\|en` | Temporarily override the language for this run (CLI and browser default language) |

---

## HTTP API

Open to the LAN / local machine, default port `8849` (can be changed or disabled in settings).

- `GET /` — service description
- `GET /v1/models`, `POST /v1/chat/completions` — OpenAI-compatible
- `/api/*` — Ollama native API proxy
- The model name can be written as `model ID` or as `partition name/model ID`
- Supports Bearer Key authentication, CORS, and LAN listening

---

## Data, Storage & Backup

| Path | Contents |
| --- | --- |
| `data/app.db` | **Single source of truth**: settings, conversations, model registry, usage, tasks (SQLite + WAL) |
| `data/settings.json` | Human-readable mirror of settings, for viewing and manual backup (the source of truth is still the database) |
| `data/images/` | Image generation artifacts (stored by task ID, including preview images) |
| `data/backups/auto-*/` | Automatic backups at startup |
| `runtime/pylib/` | In-project Python dependencies |
| `runtime/logs/` | Runtime logs (including `errors.log`) |
| `runtime/home/.ollama/` | Project-isolated Ollama runtime directory |
| `runtime/sdcpp/` | stable-diffusion.cpp executables and CUDA runtime libraries |

Everything is inside the project folder; deleting the entire directory completes a thorough cleanup (if model directories point to an external disk, they must be cleaned up separately).

---

## CLI Dashboard

At startup, a staged animation plays: kernel boot → Logo reveal → version badge → system self-check → hardware scan → charging → READY burst, then it seamlessly switches to the real-time dashboard:

- **System**: CPU / memory / GPU / VRAM (including graphics card model and temperature)
- **Current model**: status, progress, stage, context, VRAM usage, load time
- **Engine**: engine ports and status for each partition, API service address
- **Usage & tasks**: today's / cumulative usage, average speed, first token, tasks in progress
- **Live logs**: scrolling logs; `Ctrl+C` to exit (closing the browser does not affect background operation)

Terminals that do not support the fullscreen animation (dumb terminal / pipe / small window / `--plain`) automatically degrade to a line-by-line concise mode.

---

## FAQ

**Q: What should I do if the port is occupied?**
At startup, an available port is automatically searched for after the preferred port; you can also specify one with `--port N`, or change it in Settings → Interface Service.

**Q: The UI won't open / shows a blank screen?**
Make sure the command-line window is still running (closing that window terminates the backend); then make sure antivirus software is not blocking the port listening.

**Q: The model list doesn't show the model I just downloaded?**
Click "Rescan" in "Model List"; if the model is in a custom partition, make sure the partition path is correct.

**Q: What does "MTP —" mean?**
It means the GGUF has no `nextn.* / mtp.*` tensors or `nextn_predict_layers` declaration, so the engine cannot enable speculative decoding—this is a limitation of the file itself, and the marker is accurate.

**Q: How do I completely reset?**
The settings page has "Restore All Defaults"; at the data level, deleting `data/app.db` clears conversations / usage / model registry (please back up first).

**Q: Can I run multiple instances?**
Yes, but you need different UI ports, API ports, and engine starting ports, and sharing the same data directory will cause them to overwrite each other, so it is recommended to copy the project directory.

---

## Development & Testing

Under `tests/` are live-test scripts; most require starting `app-cn.py` first:

| Script | Purpose |
| --- | --- |
| `smoke_api.py` | Backend API smoke test |
| `regression.py` | Main flow regression |
| `ui_flow.py` | UI interaction (floating window, model switching, send / stop, HTML preview, formulas) |
| `console_pty.py` / `console_dumb.py` | CLI interface and degraded paths |
| `launch_real.py` | Start in the real way and self-check |
| `mtp_*.py` | A/B and end-to-end verification of MTP speculative decoding |
| `settings_persist.py` | Settings persistence |
| `e2e_image.py` / `probe_*.py` | Image generation pipeline |

The frontend consists of **build-step-free** native ES modules; after changes, just refresh for them to take effect (static assets are forcibly not cached).

---

## Design Notes

- **UI**: Dark-first, avoiding blue-purple / gold; the top navigation uses a custom-drawn liquid glass slider (spring-driven, velocity deformation, edge refraction highlights), and the select model / context / parameters / thinking buttons in the input area use 3D skeuomorphism + elastic press.
- **Bilingual implementation (frontend)**: The source code is always written with the original Chinese text; in English mode, the runtime i18n layer replaces text and tooltip attributes at the DOM level, with word lists stored in `web/static/js/i18n/`. Chinese mode has zero overhead, can be switched back at any time, and translation changes will not break existing interaction logic.
- **Bilingual implementation (backend)**: Also uses the original Chinese text as keys; `backend/i18n.py` provides `T()`, and word lists are split into `backend/i18n_parts/*.py` maintained by module. CLI text uses the startup language; HTTP request text is determined by `X-Lang`, thus staying consistent with the browser UI.
- **Language-independent content**: Partition names, model note names, disk paths, conversation titles, custom prompt presets, GGUF field values, etc. are user data and remain unchanged in any language.
- **Configuration**: SQLite is the single source of truth; `settings.json` is only a mirror, avoiding inconsistency between manual edits and program state.

---

## Version

Version history and each change are detailed in [CHANGELOG.md](CHANGELOG.md).
The current version is v1.1.31b — a concentrated fix of 22 defects (model sync, GGUF import, API authentication, chat parameters, image generation, and statistics), plus additional fixes for the context floating window failing to open when clamped by the model's upper limit and for preset levels exceeding the limit.

---

## Contact

- **Email**: dvdvjvb@163.com

If you have questions, suggestions, or want to report bugs, feel free to contact by email.

---

## Acknowledgements

- Official Ollama repository: [https://github.com/ollama/ollama)