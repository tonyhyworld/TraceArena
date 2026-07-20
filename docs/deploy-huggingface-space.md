# Deploy the public demo to Hugging Face Spaces

The default public Space uses the free **Static** SDK. It runs a deterministic,
browser-local replay from `deploy/huggingface-static/`: two agents act on
reviewed synthetic evidence, the world applies events and settlements, and the
browser calculates a SHA-256 digest for the canonical trajectory. There is no
server process and no model, provider, API-key, path, tool, upload, brokerage,
or code-execution input.

The live demo is available at
[tonyworld888/tracearena-demo](https://huggingface.co/spaces/tonyworld888/tracearena-demo).

The demo links directly to the current [v0.1.10 Capital Market Public
Edition](https://github.com/tonyhyworld/TraceArena/releases/tag/v0.1.10) and its
[scenario pack](https://github.com/tonyhyworld/TraceArena/tree/main/backend/scenarios/capital_market)
so visitors can move from the safe replay to a local, configurable run.

The root `Dockerfile` remains the richer public replay boundary for accounts
that can host Docker Spaces. It runs `app.public_demo_server:app` on
`0.0.0.0:7860` as an unprivileged user and accepts only a locale. Hugging Face
currently requires a PRO subscription for new Docker or Gradio CPU Spaces;
the Static demo is the no-server, no-subscription deployment path.

The local developer console remains available through `docker compose up`; the
Compose command overrides the public entry point and maps it only to
`127.0.0.1:8000`.

## One-time setup

1. Create a public Static Space named `tracearena-demo` under the Hugging Face
   account `tonyworld888`.
2. Create a Hugging Face access token with write access to that Space.
3. In `tonyhyworld/TraceArena`, add the token as the Actions secret `HF_TOKEN`.
4. Run the `Deploy Hugging Face Space` workflow manually.

The workflow creates an isolated repository from
`deploy/huggingface-static/` and force-pushes only that minimal snapshot to the
Space. The token is read only from the encrypted GitHub Actions secret.

## Local verification

```bash
python3 -m http.server 7860 --directory deploy/huggingface-static
```

Open `http://127.0.0.1:7860`, run the AI world, and verify that the status is
`VERIFIED`, the trajectory contains three steps, and the SHA-256 field is set.

For the Docker variant, build the root `Dockerfile` and verify
`/api/health` reports `public-replay-only`.
