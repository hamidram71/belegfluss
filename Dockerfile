# syntax=docker/dockerfile:1

# --- Build a wheel in a throwaway stage ---------------------------------------------
FROM python:3.12-slim AS build
WORKDIR /src
RUN pip install --no-cache-dir build==1.2.2
COPY pyproject.toml README.md ./
COPY src ./src
RUN python -m build --wheel --outdir /dist

# --- Runtime image: only the API and its dependencies, running as non-root ----------
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    BELEGFLUSS_STORAGE_DIR=/app/var/documents
RUN useradd --create-home --uid 10001 app
WORKDIR /app
COPY --from=build /dist/*.whl /tmp/
RUN pip install --no-cache-dir /tmp/*.whl && rm /tmp/*.whl \
    && mkdir -p /app/var/documents && chown -R app:app /app
USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')"
CMD ["uvicorn", "belegfluss.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
