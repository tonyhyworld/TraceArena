FROM python:3.11-slim
WORKDIR /app
COPY pyproject.toml uv.lock README.md LICENSE ./
COPY backend ./backend
COPY examples ./examples
COPY frontend/demo_web ./frontend/demo_web
RUN pip install --no-cache-dir .
EXPOSE 8000
CMD ["uvicorn", "app.demo_server:app", "--host", "127.0.0.1", "--port", "8000"]
