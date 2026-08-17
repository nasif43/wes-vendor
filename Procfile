web: gunicorn -k uvicorn.workers.UvicornWorker -w 2 --timeout 120 --bind 0.0.0.0:${PORT:-8000} app.main:app
