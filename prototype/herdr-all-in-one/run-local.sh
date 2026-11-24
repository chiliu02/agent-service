#!/bin/sh
# Build, start Postgres with agent-service's schema, start one container, seed four worktrees.
# usage: ./run-local.sh <ssh-public-key-file>
set -eu
HERE="$(cd "$(dirname "$0")" && pwd)"
DDL="$HERE/../../spec/database/agent-service-d3f9a0c15e27.sql"   # read, never written
docker build -q -t herdr-proto:dev "$HERE" >/dev/null
docker rm -f herdr-proto herdr-proto-db >/dev/null 2>&1 || true
docker network inspect herdr-proto-net >/dev/null 2>&1 || docker network create herdr-proto-net >/dev/null

docker run -d --name herdr-proto-db --network herdr-proto-net \
  -e POSTGRES_PASSWORD=proto -e POSTGRES_DB=agent_service postgres:17-alpine >/dev/null
until docker exec herdr-proto-db pg_isready -U postgres -d agent_service >/dev/null 2>&1; do sleep 0.5; done
docker exec -i herdr-proto-db psql -q -v ON_ERROR_STOP=1 -U postgres -d agent_service < "$DDL" >/dev/null

docker run -d --name herdr-proto --network herdr-proto-net \
  -p 127.0.0.1:18480:8080 -p 127.0.0.1:12222:2222 \
  -e AUTHORIZED_KEYS="$(cat "$1")" \
  -e AGENT_ID="${AGENT_ID:-proto-agent-1}" \
  -e PROTO_STUB="${PROTO_STUB:-1}" -e PROTO_PI_MODEL -e PROTO_WORKTREE_LOCK \
  -e ANTHROPIC_API_KEY -e OPENAI_API_KEY -e GEMINI_API_KEY \
  -e AGENT_SERVICE_DATABASE_URL=postgresql://postgres:proto@herdr-proto-db:5432/agent_service \
  --security-opt seccomp=unconfined --pids-limit 512 \
  herdr-proto:dev >/dev/null
until curl -sf localhost:18480/healthz >/dev/null; do sleep 0.5; done
docker exec herdr-proto sh -c 'cd /work && for d in wt-a wt-b wt-c wt-d; do mkdir -p $d
  printf "# Project\n\nAnswer briefly.\n" > $d/AGENTS.md; echo "@AGENTS.md" > $d/CLAUDE.md; git -C $d init -q; done'
echo "http://localhost:18480  ssh -p 12222 ubuntu@localhost  db: docker exec -it herdr-proto-db psql -U postgres agent_service"
