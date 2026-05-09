# LinkedIn Scrapper — Python + headless Chromium, runs the web UI by default.
# The Container Apps Job overrides the command to run runner_job.py instead.

FROM python:3.11-slim

# Chromium + driver + the bare minimum system libs Selenium needs.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        chromium \
        chromium-driver \
        fonts-liberation \
        ca-certificates \
        tini \
    && rm -rf /var/lib/apt/lists/*

ENV CHROME_BIN=/usr/bin/chromium \
    CHROMEDRIVER=/usr/bin/chromedriver \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8000

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

# tini reaps zombie chromedriver processes between scrape pages.
ENTRYPOINT ["/usr/bin/tini", "--"]

# Default: run the Flask web UI under gunicorn.
# Container Apps Job overrides this with: python runner_job.py
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "1", "--threads", "4", "--timeout", "120", "app:app"]
