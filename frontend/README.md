# TraceArena full frontend

This directory contains the full Vue/Vite frontend used by the local AI World
runtime. It is the operator console, audience renderer, authentication flow,
scenario factory, run archive, analysis views, bilingual UI, and replay
presentation—not the small static marketing demo in `frontend/public_demo`.

## Run locally

The repository now includes the TraceArena OS backend required by the full
frontend. The static public demo remains available separately and does not
require an API key or broker connection.

For the complete local experience, use the root launcher after installation:

```bash
./scripts/start.sh
```

It starts the OS on port 8001 and this frontend on port 5173. The default
checked-in `backend/framework.public.yaml` uses mock providers and disables
external MCP/network access, so the first run needs no model or broker key.
Create a local account in another terminal with:

```bash
cd backend && ../.venv/bin/python scripts/create_user.py
```

The backend provides the authenticated API and WebSocket routes used by the
console (`/auth/*`, `/operator/*`, `/ws`, and related routes).

```bash
cd frontend
npm ci
cp .env.example .env.local
npm run dev -- --host 127.0.0.1
```

Then open <http://127.0.0.1:5173>. Configure `VITE_API_BASE` and `VITE_WS_URL`
in `.env.local` when the OS backend is hosted elsewhere. Never commit `.env`,
`.env.local`, API keys, tokens, or `node_modules`.

## Production build

```bash
npm ci
npm run build
npm run preview -- --host 127.0.0.1
```

The generated `dist/` directory is a build artifact and is intentionally not
committed. For the backend/runtime contract, start with the repository quick
start and backend documentation.
