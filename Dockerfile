# syntax=docker/dockerfile:1.7
FROM python:3.13-slim@sha256:09a17cad02668ae61ece136b4fd36ac3849e14f670ebedb637ea3e15580525bc AS builder
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /build
COPY requirements.txt .
# Optional build secret `pip_ca` = extra CA bundle, for builds behind a TLS-inspecting proxy:
#   docker build --secret id=pip_ca,src=/path/to/ca-bundle.crt .
RUN --mount=type=secret,id=pip_ca,required=false \
    if [ -f /run/secrets/pip_ca ]; then export PIP_CERT=/run/secrets/pip_ca; fi; \
    python -m venv /opt/venv && /opt/venv/bin/pip install -r requirements.txt

FROM python:3.13-slim@sha256:09a17cad02668ae61ece136b4fd36ac3849e14f670ebedb637ea3e15580525bc AS runtime
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH" \
    APP_ENV=production \
    FLASK_APP=wsgi.py \
    PORT=8080
# Non-root user with a fixed UID so Kubernetes `runAsNonRoot` can verify it.
RUN groupadd --system --gid 10001 app && useradd --system --uid 10001 --gid app --home-dir /app --shell /usr/sbin/nologin app
WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
COPY --chown=app:app lumieree ./lumieree
COPY --chown=app:app migrations ./migrations
COPY --chown=app:app templates ./templates
COPY --chown=app:app wsgi.py ./
RUN mkdir -p static && chown app:app static
USER 10001:10001
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=3s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,os; urllib.request.urlopen('http://127.0.0.1:%s/healthz' % os.environ.get('PORT','8080'), timeout=2)"
# Schema migrations run as a separate step (Kubernetes Job / compose `migrate` service), never at web start-up,
# so several replicas cannot race each other.
CMD ["sh", "-c", "exec gunicorn wsgi:app --no-control-socket --worker-tmp-dir /dev/shm --bind 0.0.0.0:${PORT} --workers ${WEB_CONCURRENCY:-3} --threads 2 --timeout 60 --access-logfile - --error-logfile -"]
