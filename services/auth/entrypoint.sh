#!/bin/sh
set -eu

install -d -m 700 -o 10001 -g 10001 /run/keys
install -m 600 -o 10001 -g 10001 /run/secrets/jwt_private.pem /run/keys/jwt_private.pem
install -m 600 -o 10001 -g 10001 /run/secrets/jwt_public.pem /run/keys/jwt_public.pem

exec setpriv --reuid 10001 --regid 10001 --clear-groups /bin/sh -ec '
    alembic -c /app/services/auth/alembic.ini upgrade head
    exec uvicorn market_auth.main:app --host 0.0.0.0 --port 8000 --workers 1
'
