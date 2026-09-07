FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    STOCKFINDER_DATA_DIR=/data \
    STOCKFINDER_HISTORY_MAX_AGE_HOURS=18 \
    PORT=8501

RUN useradd --create-home --uid 10001 stockfinder \
    && mkdir -p /app /data \
    && chown -R stockfinder:stockfinder /app /data

WORKDIR /app

COPY --chown=stockfinder:stockfinder pyproject.toml README.md ./
COPY --chown=stockfinder:stockfinder src ./src

RUN python -m pip install --upgrade pip \
    && python -m pip install .

USER stockfinder

EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\", \"8501\")}/_stcore/health', timeout=3)"

CMD ["sh", "-c", "python -m streamlit run streamlit_app.py --server.address=0.0.0.0 --server.port=${PORT:-8501}"]
