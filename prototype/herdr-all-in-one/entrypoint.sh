#!/bin/sh
# Prototype entrypoint: per-CLI config, the stub model (optional), a non-root
# sshd for the remote Herdr client, the headless Herdr server, then the shim.
set -eu

STUB_PORT=47400
: "${PROTO_STUB:=1}"            # 1: every CLI talks to the in-container stub model
: "${PROTO_HTTP_PORT:=8080}"
: "${PROTO_SSH_PORT:=2222}"

if [ "$PROTO_STUB" = 1 ]; then
  export ANTHROPIC_BASE_URL="http://127.0.0.1:${STUB_PORT}"
  export ANTHROPIC_AUTH_TOKEN="${ANTHROPIC_AUTH_TOKEN:-stub}"
  export ANTHROPIC_API_KEY="${ANTHROPIC_API_KEY:-stub}"   # pi reads this one
  export OPENAI_API_KEY="${OPENAI_API_KEY:-stub}"
  export GEMINI_API_KEY="${GEMINI_API_KEY:-stub}"
  export GOOGLE_GEMINI_BASE_URL="http://127.0.0.1:${STUB_PORT}"
  OPENAI_BASE="http://127.0.0.1:${STUB_PORT}/v1"
  python3 -I /opt/proto/stub_llm.py "$STUB_PORT" > /tmp/stub_llm.log 2>&1 &
else
  OPENAI_BASE="${OPENAI_BASE_URL:-https://api.openai.com/v1}"
fi

# --- Herdr: no network checks, so behaviour moves only with the image --------
mkdir -p "$XDG_CONFIG_HOME/herdr"
cat > "$XDG_CONFIG_HOME/herdr/config.toml" <<EOF
[update]
version_check = false
manifest_check = false
EOF

# --- Codex: a provider that reads its key from the env -----------------------
mkdir -p "$CODEX_HOME"
touch "$CODEX_HOME/config.toml"
if ! grep -q '^model_provider' "$CODEX_HOME/config.toml"; then
  tmp=$(mktemp)
  cat > "$tmp" <<EOF
model_provider = "gw"
model = "gpt-5"
sandbox_mode = "danger-full-access"
approval_policy = "never"
check_for_update_on_startup = false
[model_providers.gw]
name = "gw"
base_url = "${OPENAI_BASE}"
wire_api = "responses"
env_key = "OPENAI_API_KEY"
request_max_retries = 0
stream_max_retries = 0
EOF
  cat "$CODEX_HOME/config.toml" >> "$tmp"   # keeps the hooks the Herdr integration wrote
  mv "$tmp" "$CODEX_HOME/config.toml"
fi
# Herdr's integration hook makes Codex open a "Hooks need review" dialog, which
# Herdr itself reads as `idle`. Pre-trust it. The hash is what Codex 0.146.0
# recorded for the hooks.json this image's `herdr integration install codex`
# writes; a Herdr or Codex bump can change it, and then the dialog comes back.
if ! grep -q '^\[hooks.state' "$CODEX_HOME/config.toml"; then
  cat >> "$CODEX_HOME/config.toml" <<'EOF'

[hooks.state."/home/ubuntu/.codex/hooks.json:session_start:0:0"]
trusted_hash = "sha256:989b0d289e03fa6eabdf71910b4213746007a747f90db8d7b4f130f0904862b7"
EOF
fi

# --- Pi: anthropic provider pointed at the gateway (or stub) -----------------
mkdir -p "$PI_CODING_AGENT_DIR"
cat > "$PI_CODING_AGENT_DIR/models.json" <<EOF
{"providers":{"anthropic":{"baseUrl":"${ANTHROPIC_BASE_URL:-https://api.anthropic.com}"}}}
EOF

# --- Gemini: API-key auth, and AGENTS.md as the one project file -------------
mkdir -p "$GEMINI_CLI_HOME/.gemini"
cat > "$GEMINI_CLI_HOME/.gemini/settings.json" <<EOF
{"security":{"auth":{"selectedType":"gemini-api-key"}},
 "context":{"fileName":["AGENTS.md"]},
 "general":{"disableAutoUpdate":true,"disableUpdateNag":true},
 "privacy":{"usageStatisticsEnabled":false},
 "hooksConfig":{"enabled":true},
 "hooks":{"SessionStart":[{"matcher":"*","hooks":[
   {"name":"herdr-session","type":"command","command":"python3 -I /opt/proto/gemini_session_hook.py","timeout":5000}]}]}}
EOF

# --- sshd as uid 1000: it can only log in its own user, which is the point ---
SSHD_DIR="$HOME/.sshd"
mkdir -p "$SSHD_DIR" "$HOME/.ssh"
chmod 700 "$HOME/.ssh"
[ -f "$SSHD_DIR/host_ed25519" ] || ssh-keygen -q -t ed25519 -N '' -f "$SSHD_DIR/host_ed25519"
printf '%s\n' "${AUTHORIZED_KEYS:-}" > "$HOME/.ssh/authorized_keys"
chmod 600 "$HOME/.ssh/authorized_keys"
cat > "$SSHD_DIR/sshd_config" <<EOF
Port ${PROTO_SSH_PORT}
HostKey ${SSHD_DIR}/host_ed25519
PidFile ${SSHD_DIR}/sshd.pid
AuthorizedKeysFile ${HOME}/.ssh/authorized_keys
PasswordAuthentication no
KbdInteractiveAuthentication no
PubkeyAuthentication yes
UsePAM no
PermitRootLogin no
AllowUsers ubuntu
AllowTcpForwarding no
X11Forwarding no
PermitUserEnvironment no
SetEnv HERDR_SOCKET_PATH=${XDG_CONFIG_HOME}/herdr/herdr.sock XDG_CONFIG_HOME=${XDG_CONFIG_HOME}
EOF
/usr/sbin/sshd -f "$SSHD_DIR/sshd_config" -E /tmp/sshd.log

# --- the headless Herdr server: every pane inherits THIS env -----------------
herdr server > /tmp/herdr-server.log 2>&1 &
i=0
until herdr status >/dev/null 2>&1; do
  i=$((i + 1)); [ $i -gt 100 ] && { cat /tmp/herdr-server.log; exit 1; }
  sleep 0.1
done

# Not -I: the shim imports usage.py and store.py from its own directory.
exec /opt/proto/venv/bin/python /opt/proto/shim.py "$PROTO_HTTP_PORT"
