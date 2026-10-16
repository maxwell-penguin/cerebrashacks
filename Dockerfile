FROM python:3.11-slim

WORKDIR /app

# Chromium system libs for the screenshot renderer (auto-refine / visual QA)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 \
    libdbus-1-3 libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 \
    libxrandr2 libgbm1 libpango-1.0-0 libcairo2 libasound2 \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Browsers go in a shared path so the non-root user can launch them
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
RUN playwright install chromium && chmod -R a+rX /ms-playwright

COPY backend/ .

# Non-root user; /data is where the SQLite file lives (owned by app so a fresh named volume is writable)
RUN useradd --create-home --uid 10001 app && mkdir /data && chown app /data
ENV DB_PATH=/data/runs.db
USER app

EXPOSE 8000

# init_db first so the schema exists before the first request, then hand PID 1 to uvicorn
CMD ["sh", "-c", "python -c 'import db; db.init_db()' && exec uvicorn main:app --host 0.0.0.0 --port 8000"]
