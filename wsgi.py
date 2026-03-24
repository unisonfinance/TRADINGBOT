"""
WSGI entry point — used by Gunicorn (production) and Vercel (serverless).

Local dev:
    python wsgi.py

Production (Gunicorn):
    gunicorn wsgi:app --bind 0.0.0.0:$PORT --workers 1 --threads 4

Vercel:
    Handled automatically via vercel.json
"""
import os
import sys

# Ensure project root is on path regardless of working directory
ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from web.app import app  # noqa: E402 — must come after path fix

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5050))
    debug = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
    app.run(host="0.0.0.0", port=port, debug=debug)
