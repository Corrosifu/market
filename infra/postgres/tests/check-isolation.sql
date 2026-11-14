-- Contrôle sans secret : exécuter avec psql -v ON_ERROR_STOP=1 -U postgres -d market.
DO $$
DECLARE
    schemas text[] := ARRAY['auth', 'orders', 'inventory', 'payment', 'delivery', 'realtime'];
    own_schema text;
    other_schema text;
    service_role text;
BEGIN
    FOREACH own_schema IN ARRAY schemas LOOP
        service_role := own_schema || '_svc';
        IF NOT EXISTS (
            SELECT 1 FROM pg_roles
            WHERE rolname = service_role AND rolcanlogin
              AND NOT rolsuper AND NOT rolcreatedb AND NOT rolcreaterole
              AND NOT rolreplication AND NOT rolbypassrls
        ) THEN
            RAISE EXCEPTION 'Rôle de connexion trop privilégié ou absent : %', service_role;
        END IF;
        IF NOT EXISTS (
            SELECT 1 FROM pg_namespace
            WHERE nspname = own_schema AND nspowner = service_role::regrole
        ) THEN
            RAISE EXCEPTION 'Propriétaire incorrect : %', own_schema;
        END IF;
        IF NOT EXISTS (
            SELECT 1 FROM pg_db_role_setting AS settings
            JOIN pg_database AS db ON db.oid = settings.setdatabase
            WHERE db.datname = 'market' AND settings.setrole = service_role::regrole
              AND ('search_path=' || own_schema) = ANY(settings.setconfig)
        ) THEN
            RAISE EXCEPTION 'search_path incorrect pour % dans market', service_role;
        END IF;
        IF NOT has_database_privilege(service_role, 'market', 'CONNECT')
           OR has_database_privilege(service_role, 'market', 'CREATE')
           OR has_database_privilege(service_role, 'market', 'TEMP') THEN
            RAISE EXCEPTION 'Droits de base incorrects : %', service_role;
        END IF;
        IF NOT has_schema_privilege(service_role, own_schema, 'USAGE')
           OR NOT has_schema_privilege(service_role, own_schema, 'CREATE') THEN
            RAISE EXCEPTION 'Schéma propre inutilisable : %', service_role;
        END IF;
        FOREACH other_schema IN ARRAY schemas || ARRAY['public'] LOOP
            IF other_schema <> own_schema AND (
                has_schema_privilege(service_role, other_schema, 'USAGE')
                OR has_schema_privilege(service_role, other_schema, 'CREATE')
            ) THEN
                RAISE EXCEPTION 'Accès croisé interdit : % vers %', service_role, other_schema;
            END IF;
        END LOOP;
    END LOOP;
END;
$$;
