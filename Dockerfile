# CreditLens API — serves curated companies, metrics and loan scenarios.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    CREDITLENS_CURATED=/app/backend/data/curated
WORKDIR /app

COPY requirements-api.txt .
RUN pip install --no-cache-dir -r requirements-api.txt

COPY backend ./backend
COPY configs ./configs

RUN useradd --create-home appuser
USER appuser

EXPOSE 8000
# Render/Fly/Railway inject $PORT; default 8000 locally
CMD ["sh", "-c", "uvicorn backend.app.api.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
