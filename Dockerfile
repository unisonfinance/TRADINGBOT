FROM python:3.11-slim

WORKDIR /app

# System deps for pandas/numpy wheels
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# If FIREBASE_SA_JSON env var is set, write it to service_account.json
# (so we don't have to commit secrets to git)
RUN echo '#!/bin/sh\n\
if [ -n "$FIREBASE_SA_JSON" ]; then\n\
  echo "$FIREBASE_SA_JSON" > /app/service_account.json;\n\
fi\n\
exec "$@"' > /app/entrypoint.sh && chmod +x /app/entrypoint.sh

ENTRYPOINT ["/app/entrypoint.sh"]
CMD sh -c "gunicorn wsgi:app --bind 0.0.0.0:${PORT:-5050} --workers 1 --threads 4 --timeout 120"
