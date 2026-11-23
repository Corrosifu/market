# Image du service order. Contexte de construction : la racine du dépôt (workspace uv).
#   docker build -f services/order/Dockerfile .
FROM python:3.12.10-slim

# uv à une version exacte (celle qui a produit uv.lock).
RUN pip install --no-cache-dir --root-user-action=ignore uv==0.13.8

ENV UV_COMPILE_BYTECODE=1 \
    UV_NO_CACHE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:${PATH}"

WORKDIR /app

# 1. Métadonnées du workspace uv (toutes exigées par `uv sync --frozen --package`), puis dépendances seules :
#    cette couche ne change que si le verrou ou un pyproject change.
COPY pyproject.toml uv.lock ./
COPY libs/market_common/pyproject.toml libs/market_common/pyproject.toml
COPY services/auth/pyproject.toml services/auth/pyproject.toml
COPY services/catalog/pyproject.toml services/catalog/pyproject.toml
COPY services/order/pyproject.toml services/order/pyproject.toml
COPY services/inventory/pyproject.toml services/inventory/pyproject.toml
COPY services/payment/pyproject.toml services/payment/pyproject.toml
COPY services/delivery/pyproject.toml services/delivery/pyproject.toml
COPY services/dashboard_api/pyproject.toml services/dashboard_api/pyproject.toml
RUN uv sync --frozen --package market-order --no-dev --no-install-workspace

# 2. Code : la bibliothèque commune (sans ses tests) et le service seul (ni .env, ni clés, ni code des autres
#    services). Les migrations sont embarquées dans le dossier de ce service.
COPY libs/market_common/market_common libs/market_common/market_common
COPY services/order services/order
RUN uv sync --frozen --package market-order --no-dev \
    && useradd --system --uid 10001 --create-home --shell /usr/sbin/nologin market

# Code et dépendances appartiennent à root : l'utilisateur applicatif ne peut que les lire.
ENV HOME=/home/market
USER market

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=3s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2).status == 200 else 1)"]

CMD ["sh", "-c", "alembic -c /app/services/order/alembic.ini upgrade head && exec uvicorn market_order.main:app --host 0.0.0.0 --port 8000 --workers 1 --no-server-header"]
