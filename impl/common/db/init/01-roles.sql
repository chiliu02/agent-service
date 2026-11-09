-- Roles for the agent-service database.
--
-- TWO roles, because the agent is inside this service's trust boundary.
-- `persistence.md` §"The credential-leak interaction" is the reasoning; the
-- short version is that the agent's subprocess inherits the service process's
-- environment and has `Bash`, so a credential left reachable is a credential
-- the agent has. `config.get_settings()` pops the service URL out of the
-- environment at startup, and this split is what limits the damage if that is
-- ever bypassed.
--
-- Runs once, on an EMPTY data directory. `postgres:17`'s entrypoint ignores
-- /docker-entrypoint-initdb.d entirely when the volume already has a database,
-- so editing this file does nothing to an existing deployment -- recreate the
-- volume or apply the change by hand.

-- The service. Owns its schema; Alembic runs as this role.
CREATE ROLE agent_service LOGIN PASSWORD 'change-me-in-env';
GRANT ALL ON SCHEMA public TO agent_service;
ALTER SCHEMA public OWNER TO agent_service;

-- The agent, if it is ever given database access at all (persistence.md Part B
-- / Q10 -- NOT enabled by anything today). Deliberately created with no table
-- grants: a role that can log in and see nothing is a much smaller problem
-- than one granted access before anyone decided what it should see.
CREATE ROLE agent_readonly LOGIN PASSWORD 'change-me-in-env';
GRANT CONNECT ON DATABASE agent TO agent_readonly;
GRANT USAGE ON SCHEMA public TO agent_readonly;

-- Explicitly NOT granted here:
--   GRANT SELECT ON ALL TABLES IN SCHEMA public TO agent_readonly;
-- Enabling Part B means choosing WHICH tables, which is Q10's decision. Note
-- that `transcript_entries` and `events` contain the agent's own conversations
-- across every session -- granting blanket SELECT would let anything holding
-- this role read every session's transcript, not just its own.
