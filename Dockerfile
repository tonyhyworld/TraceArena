FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TRACEARENA_ROOT=/app
WORKDIR /app
COPY pyproject.toml uv.lock README.md LICENSE ./
COPY backend ./backend
COPY examples ./examples
COPY frontend/demo_web ./frontend/demo_web
COPY frontend/public_demo ./frontend/public_demo
RUN pip install --no-cache-dir .
RUN useradd --create-home --uid 1000 tracearena
USER tracearena
EXPOSE 7860
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:7860/api/health', timeout=3)"
CMD ["uvicorn", "app.public_demo_server:app", "--host", "0.0.0.0", "--port", "7860", "--workers", "1"]
