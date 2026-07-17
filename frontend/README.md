# TraceArena full frontend

This directory contains the full Vue/Vite frontend used by the local AI World
runtime. It is the operator console, audience renderer, authentication flow,
scenario factory, run archive, analysis views, bilingual UI, and replay
presentation—not the small static marketing demo in `frontend/public_demo`.

## Run locally

The full frontend expects the TraceArena OS backend to be running on port 8001.
The backend must provide the authenticated API and WebSocket routes used by the
console (`/auth/*`, `/api/*`, and `/ws`). The static public demo remains
available separately and does not require an API key or broker connection.

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
