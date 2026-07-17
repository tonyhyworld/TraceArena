# Deploy the public replay demo to Hugging Face Spaces

The root `Dockerfile` is the public deployment boundary. It runs
`app.public_demo_server:app` on `0.0.0.0:7860` as an unprivileged user. The
public API accepts only a locale and always executes the reviewed deterministic
fixture. It does not accept model, provider, API-key, path, tool, upload, or
code-execution input.

The local developer console remains available through `docker compose up`; the
Compose command overrides the public entry point and maps it only to
`127.0.0.1:8000`.

## One-time setup

1. Create a public Docker Space named `tracearena-demo` under the Hugging Face
   account `tonyworld888`.
2. Create a Hugging Face access token with write access to that Space.
3. In `tonyhyworld/TraceArena`, add the token as the Actions secret `HF_TOKEN`.
4. Run the `Deploy Hugging Face Space` workflow manually.

The workflow creates an orphan deployment commit, replaces the GitHub README
with `deploy/huggingface/README.md`, and force-pushes that snapshot to the Space.
The token is read only from the encrypted GitHub Actions secret.

## Local verification

```bash
docker build -t tracearena-public-demo .
docker run --rm -p 127.0.0.1:7860:7860 tracearena-public-demo
```

Open `http://127.0.0.1:7860` and verify `/api/health` reports
`public-replay-only`.
