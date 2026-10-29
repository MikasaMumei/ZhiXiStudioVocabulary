#!/bin/sh
set -eu
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<'SQL'
\getenv app_password ENGLISHWORDS_DB_PASSWORD
\getenv target_database POSTGRES_DB
SELECT format('CREATE ROLE englishwords_app LOGIN PASSWORD %L', :'app_password') \gexec
SELECT format('GRANT CONNECT ON DATABASE %I TO englishwords_app', :'target_database') \gexec
GRANT USAGE, CREATE ON SCHEMA public TO englishwords_app;
SQL
