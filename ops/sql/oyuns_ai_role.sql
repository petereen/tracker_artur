-- OYUNS AI agent: its own least-privilege database role (AI_DATABASE_URL).
--
-- The agent opens a separate connection pool per tenant through this role
-- (app/services/ai_gateway/tenant_db.py) and every transaction sets
-- app.tenant_id + app.rls_strict = on. Because the role is NOSUPERUSER and
-- NOBYPASSRLS, PostgreSQL row-level security physically limits each agent
-- query to the asking tenant, even while the API itself still connects as
-- the schema owner. Set AI_DATABASE_REQUIRE_RLS=true once it is in place.
--
-- Run as the owner, replacing the password:
--   docker compose exec -T db psql -U tracker -d sales_tracker \
--     -v ai_password="'<strong password>'" -f - < ops/sql/oyuns_ai_role.sql
-- then set AI_DATABASE_URL=postgresql+asyncpg://oyuns_ai:<password>@db:5432/sales_tracker

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'oyuns_ai') THEN
    CREATE ROLE oyuns_ai LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
  END IF;
END
$$;
ALTER ROLE oyuns_ai WITH PASSWORD :ai_password;
ALTER ROLE oyuns_ai NOSUPERUSER NOBYPASSRLS;
-- Nothing is visible without an explicit tenant or declared system context.
ALTER ROLE oyuns_ai SET app.rls_strict = 'on';

GRANT CONNECT ON DATABASE :"DBNAME" TO oyuns_ai;
GRANT USAGE ON SCHEMA public TO oyuns_ai;
-- The agent reads company data and writes only its own audit/preview rows;
-- RLS confines both to the tenant.
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO oyuns_ai;
GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA public TO oyuns_ai;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO oyuns_ai;
ALTER DEFAULT PRIVILEGES FOR ROLE tracker IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO oyuns_ai;
ALTER DEFAULT PRIVILEGES FOR ROLE tracker IN SCHEMA public
  GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO oyuns_ai;
ALTER DEFAULT PRIVILEGES FOR ROLE tracker IN SCHEMA public
  GRANT EXECUTE ON FUNCTIONS TO oyuns_ai;

-- Verify (expect superuser = f, bypassrls = f):
SELECT rolname, rolsuper AS superuser, rolbypassrls AS bypassrls FROM pg_roles WHERE rolname = 'oyuns_ai';
