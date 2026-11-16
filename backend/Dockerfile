FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY tryon_backend ./tryon_backend

ENV PORT=8080
EXPOSE 8080
# One worker: the generation limits are counted in memory.
CMD ["sh", "-c", "uvicorn tryon_backend.app:app_from_env --factory --host 0.0.0.0 --port ${PORT} --workers 1"]
