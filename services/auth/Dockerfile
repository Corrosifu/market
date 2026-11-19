FROM python:3.12.10-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH"
WORKDIR /app

RUN pip install --no-cache-dir uv==0.13.8 \
    && useradd --uid 10001 --user-group --create-home market

COPY pyproject.toml uv.lock ./
COPY libs/ libs/
COPY services/auth/pyproject.toml services/auth/
COPY services/catalog/pyproject.toml services/catalog/
COPY services/order/pyproject.toml services/order/
COPY services/inventory/pyproject.toml services/inventory/
COPY services/payment/pyproject.toml services/payment/
COPY services/delivery/pyproject.toml services/delivery/
COPY services/dashboard_api/pyproject.toml services/dashboard_api/
RUN uv sync --frozen --package market-auth --no-install-workspace

COPY services/auth/ services/auth/
RUN uv sync --frozen --package market-auth

ENV HOME=/home/market

# L'entrypoint copie les secrets 0600 puis remplace root par l'utilisateur applicatif.
ENTRYPOINT ["/bin/sh", "/app/services/auth/entrypoint.sh"]
