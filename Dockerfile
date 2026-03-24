FROM python:3.11-slim

WORKDIR /app

# System deps for pandas/numpy wheels
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Entrypoint: write service_account.json from env var if present, then run CMD
RUN printf '#!/bin/sh\nif [ -n "$FIREBASE_SA_JSON" ]; then\n  echo "$FIREBASE_SA_JSON" > /app/service_account.json\nfi\nexec "$@"\n' > /app/entrypoint.sh && chmod +x /app/entrypoint.sh

ENTRYPOINT ["/app/entrypoint.sh"]

# Railway injects PORT env var; default to 5050 if not set
ENV PORT=5050
EXPOSE 5050

CMD ["sh", "-c", "gunicorn wsgi:app --bind 0.0.0.0:${PORT:-5050} --workers 1 --threads 4 --timeout 120"]
