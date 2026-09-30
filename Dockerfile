FROM ghcr.io/astral-sh/uv:python3.11-bookworm-slim
WORKDIR /app
COPY . /app
RUN uv sync --locked --no-dev
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1 BALAGH_DATA_DIR=/var/lib/balagh
RUN mkdir -p /var/lib/balagh && useradd --system --uid 10001 balagh && chown -R balagh:balagh /var/lib/balagh /app
USER balagh
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "2", "--threads", "4", "--timeout", "40", "app:app"]
