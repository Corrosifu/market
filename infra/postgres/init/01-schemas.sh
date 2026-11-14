#!/bin/sh
set -eu

# psql quote chaque valeur comme littéral SQL, même si elle contient une apostrophe.
psql --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" --set ON_ERROR_STOP=1 \
  -v auth_pw="${AUTH_DB_PASSWORD:?}" \
  -v orders_pw="${ORDERS_DB_PASSWORD:?}" \
  -v inventory_pw="${INVENTORY_DB_PASSWORD:?}" \
  -v payment_pw="${PAYMENT_DB_PASSWORD:?}" \
  -v delivery_pw="${DELIVERY_DB_PASSWORD:?}" \
  -v realtime_pw="${REALTIME_DB_PASSWORD:?}" <<'SQL'
BEGIN;
REVOKE ALL ON SCHEMA public FROM PUBLIC;
REVOKE ALL ON DATABASE market FROM PUBLIC;

CREATE ROLE auth_svc LOGIN PASSWORD :'auth_pw';
CREATE ROLE orders_svc LOGIN PASSWORD :'orders_pw';
CREATE ROLE inventory_svc LOGIN PASSWORD :'inventory_pw';
CREATE ROLE payment_svc LOGIN PASSWORD :'payment_pw';
CREATE ROLE delivery_svc LOGIN PASSWORD :'delivery_pw';
CREATE ROLE realtime_svc LOGIN PASSWORD :'realtime_pw';

CREATE SCHEMA auth AUTHORIZATION auth_svc;
CREATE SCHEMA orders AUTHORIZATION orders_svc;
CREATE SCHEMA inventory AUTHORIZATION inventory_svc;
CREATE SCHEMA payment AUTHORIZATION payment_svc;
CREATE SCHEMA delivery AUTHORIZATION delivery_svc;
CREATE SCHEMA realtime AUTHORIZATION realtime_svc;

ALTER ROLE auth_svc IN DATABASE market SET search_path = auth;
ALTER ROLE orders_svc IN DATABASE market SET search_path = orders;
ALTER ROLE inventory_svc IN DATABASE market SET search_path = inventory;
ALTER ROLE payment_svc IN DATABASE market SET search_path = payment;
ALTER ROLE delivery_svc IN DATABASE market SET search_path = delivery;
ALTER ROLE realtime_svc IN DATABASE market SET search_path = realtime;

GRANT CONNECT ON DATABASE market TO auth_svc;
GRANT CONNECT ON DATABASE market TO orders_svc;
GRANT CONNECT ON DATABASE market TO inventory_svc;
GRANT CONNECT ON DATABASE market TO payment_svc;
GRANT CONNECT ON DATABASE market TO delivery_svc;
GRANT CONNECT ON DATABASE market TO realtime_svc;
COMMIT;
SQL
