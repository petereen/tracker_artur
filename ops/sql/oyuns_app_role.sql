-- OYUNS ERP: least-privilege runtime role so PostgreSQL row-level security
-- is actually enforced (docs/multi-tenancy.md, "Step-by-step migration").
--
-- Row-level security never applies to superusers or BYPASSRLS roles, and the
-- docker `POSTGRES_USER` (tracker) is a superuser. Keep `tracker` as the
-- schema owner that runs Alembic (SYNC_DATABASE_URL); point the API and the
-- bot's DATABASE_URL at `oyuns_app`.
--
-- Run as the owner, replacing the password:
--   docker compose exec -T db psql -U tracker -d sales_tracker \
--     -v app_password="'<strong password>'" -f - < ops/sql/oyuns_app_role.sql

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'oyuns_app') THEN
    CREATE ROLE oyuns_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
  END IF;
END
$$;
ALTER ROLE oyuns_app WITH PASSWORD :app_password;
ALTER ROLE oyuns_app NOSUPERUSER NOBYPASSRLS;

GRANT CONNECT ON DATABASE :"DBNAME" TO oyuns_app;
GRANT USAGE ON SCHEMA public TO oyuns_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO oyuns_app;
GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA public TO oyuns_app;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO oyuns_app;

-- Tables, sequences and functions created by future migrations (owned by the
-- migration role) are granted automatically.
ALTER DEFAULT PRIVILEGES FOR ROLE tracker IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO oyuns_app;
ALTER DEFAULT PRIVILEGES FOR ROLE tracker IN SCHEMA public
  GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO oyuns_app;
ALTER DEFAULT PRIVILEGES FOR ROLE tracker IN SCHEMA public
  GRANT EXECUTE ON FUNCTIONS TO oyuns_app;

-- Optional, after every worker declares its context (phase 2): make the
-- system context explicit instead of implicit.
--   ALTER DATABASE sales_tracker SET app.rls_strict = 'on';

-- Verify (expect superuser = f, bypassrls = f):
SELECT rolname, rolsuper AS superuser, rolbypassrls AS bypassrls FROM pg_roles WHERE rolname = 'oyuns_app';
