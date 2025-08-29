# Om — Panel Meditation Coach (v1.0)

A single-file [Panel](https://panel.pyviz.org/) web app that guides a 4‑phase meditation with auto‑TTS, simple chat prompts, and a downloadable PDF certificate at the end.

This repo is the **minimal** setup for running `Om_1.0.py` locally or deploying it.

---

## Quick start (local)

**Requirements:** Python 3.9–3.11

```bash
git clone <YOUR_REPO_URL>
cd <YOUR_REPO_DIR>
python -m venv .venv
# Windows: .venv\Scripts\activate
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then edit .env
```

Edit `.env` and add your OpenAI key:

```env
OPENAI_API_KEY=sk-...
```

### Run it

**Option A — Panel server (recommended for dev):**
```bash
panel serve Om_1.0.py --address 0.0.0.0 --port 8799 --autoreload --allow-websocket-origin='*'
```
Open: http://localhost:8799

**Option B — Plain Python (the script calls `pn.serve` when run directly):**
```bash
python Om_1.0.py
```
Open: http://localhost:8799

> If the port is busy, change `--port` / the `pn.serve(... port=...)` value.

---

## What files does the app need?

**Required for local run**
- `Om_1.0.py` — the Panel app (already includes `tmpl.servable()` and `pn.serve` under `__main__`).
- `requirements.txt` — Python dependencies.
- `.env` — **not committed**; contains `OPENAI_API_KEY`.
- `README.md` — (this file) run/deploy docs.

**Nice to have**
- `.env.example` — template showing required env variables.
- `.gitignore` — ignore `__pycache__/`, `.venv/`, `.env`, etc.

No other assets are required; the app generates files in-memory (e.g., the PDF certificate via `reportlab`) and uses the OpenAI API for TTS.

---

## Deploying

### Heroku (or platforms that read a `Procfile`)

Add a `Procfile` with:
```
web: panel serve Om_1.0.py --address=0.0.0.0 --port=$PORT --allow-websocket-origin='*'
```

Optionally pin Python with `runtime.txt`, e.g.:
```
python-3.11.9
```

Set the config var in the dashboard:
```
OPENAI_API_KEY=sk-...
```

### Render

Create a **Web Service**:
- **Start command**: `panel serve Om_1.0.py --address 0.0.0.0 --port $PORT --allow-websocket-origin='*'`
- **Environment**: set `OPENAI_API_KEY`

### Docker (optional)

`Dockerfile` example:

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY Om_1.0.py ./
ENV PORT=8799
EXPOSE 8799
CMD panel serve Om_1.0.py --address 0.0.0.0 --port $PORT --allow-websocket-origin='*'
```

Build & run:
```bash
docker build -t om-panel .
docker run -p 8799:8799 -e OPENAI_API_KEY=sk-... om-panel
```

---

## Troubleshooting

- **`OPENAI_API_KEY missing`** — create `.env` or export the variable before running.
- **`FileDownload(...) got unexpected keyword 'mime_type'`** — use **Panel ≥ 1.3** (this app does not pass `mime_type`).
- **Blank page or websocket error** — ensure you used `--allow-websocket-origin='*'` (or your domain) when reverse-proxying.

---

## Tech stack

- Panel (FastListTemplate)
- OpenAI (text-to-speech)
- ReportLab (PDF certificate generation)
- python-dotenv (environment variables)
