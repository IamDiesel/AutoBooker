# AutoBooker

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![uv](https://img.shields.io/badge/package%20manager-uv-magenta)](https://github.com/astral-sh/uv)
[![Code Style: Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![Checked with mypy](https://www.mypy-lang.org/static/mypy_badge.svg)](https://mypy-lang.org/)
[![CI Pipeline](https://github.com/IamDiesel/AutoBooker/actions/workflows/ci.yml/badge.svg)](https://github.com/IamDiesel/AutoBooker/actions)

AutoBooker is a high-speed, asynchronous automated checkout and booking framework. It is designed to navigate time-critical booking releases (drops) by combining the raw execution speed of HTTP/2 API requests with the human-like interaction of a real browser for payment gateway handoffs.

Built entirely on **Clean Architecture** principles, it strictly separates domain logic (State Machine) from infrastructure implementations (`httpx` and `playwright`).

## 🚀 Key Features

*   **Hybrid Execution (Session Handoff):** Executes cart and checkout flows in milliseconds via `httpx`, then injects the live session cookies into a visible `playwright` Chromium instance for manual payment approval (e.g., PayPal) to bypass advanced anti-bot systems.
*   **Exploration Mode (Network Sniffing):** Includes a dry-run mode that opens a browser for manual navigation, passively intercepts underlying JSON API payloads, and persists them for future high-speed replay.
*   **Deterministic State Machine:** The entire booking workflow is managed by a strict state machine (`transitions`), preventing race conditions and ensuring predictable execution paths.
*   **Aggressive Retry Looping:** Built-in resilience against 5xx Server Errors (overload) during high-traffic drops.
*   **Modern FOSS Stack:** Powered by `uv`, `pydantic` v2, `structlog`, and strictly typed with `mypy`.

## 🏗️ Architecture Overview

```text
autobooker/
├── domain/           # Core business logic. Pydantic Models & State Machine. (Zero external dependencies)
├── application/      # Orchestrators/Use Cases. Controls flow based on RunModes.
├── infrastructure/   # I/O boundary. HTTPX clients, Playwright manager, File storage.
└── .data/            # Local persistence for sessions/cookies (Ignored by Git)

```

## 🛠️ Installation & Setup

This project uses [uv](https://github.com/astral-sh/uv), the extremely fast Python package and project manager written in Rust.

1. **Install uv** (if not already installed):
```bash
curl -LsSf [https://astral.sh/uv/install.sh](https://astral.sh/uv/install.sh) | sh
# Windows: powershell -c "irm [https://astral.sh/uv/install.ps1](https://astral.sh/uv/install.ps1) | iex"

```


2. **Clone and sync the project:**
```bash
git clone [https://github.com/IamDiesel/AutoBooker.git](https://github.com/IamDiesel/AutoBooker.git)
cd AutoBooker
uv sync --all-extras --dev

```


3. **Install Playwright Browsers:**
```bash
uv run playwright install chromium

```


4. **Initialize Pre-commit Hooks:**
```bash
uv run pre-commit install

```



## 🚦 Usage Modes

The system operates based on the `RunMode` defined in `main.py`:

### 1. Exploration Mode (`RunMode.EXPLORATION`)

Used to gather intelligence before a drop. The bot opens a browser and lets you navigate manually. In the background, it intercepts JSON payloads and session cookies, saving them safely to `.data/session_state.json`.

### 2. Live Attempt (`RunMode.LIVE_ATTEMPT_1`)

The high-speed execution mode. It loads the intercepted payloads, dynamically mutates the target parameters (e.g., `service_id`), and fires asynchronous HTTP/2 requests. Upon reaching the payment stage, it triggers the **Session Handoff**, opening a browser for final user confirmation.

Run the system via:

```bash
uv run python main.py

```

## 🧪 Development & Testing

We enforce strict code quality. The CI pipeline will fail if these checks do not pass.

* **Format & Lint (Ruff):** `uv run ruff check --fix .` && `uv run ruff format .`
* **Type Checking (Mypy):** `uv run mypy .`
* **Run Tests (Pytest + Respx):** `uv run pytest`

## ⚠️ Disclaimer

This tool is intended for educational purposes and personal use. Ensure compliance with the Terms of Service of any target website before running automated requests.
