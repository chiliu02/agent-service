# Does `gemini --sandbox` start INSIDE our own container?
#
# The last question `spike-findings.md` §8 left open, and the only one a
# credential could not unlock: it needs a container, because the whole point is
# what happens when the agent is ALREADY containerised -- which is how this
# platform ships every build.
#
#   docker build -f spike/sandbox-probe.Dockerfile -t gemini-sandbox-probe .
#   docker run --rm -e GEMINI_API_KEY -e GEMINI_CLI_TRUST_WORKSPACE=true \
#     gemini-sandbox-probe gemini -p "Reply with exactly: OK" -o json -s
#
# **Deliberately a plain container with no docker socket mounted**, because that
# is the shipping posture. Mounting the host's socket to make `--sandbox` work
# would hand the agent control of the host's container runtime, which is a
# strictly worse boundary than the one it is trying to add.
#
# Pinned to the version every finding in the spike was measured against.
FROM node:22-slim

RUN npm install -g @google/gemini-cli@0.54.4 \
 && gemini --version

# A non-root user, matching how the shipped builds run. HOME must be writable:
# the CLI writes session state under ~/.gemini and has no override for it.
RUN useradd -m -u 1001 agent
USER agent
WORKDIR /work
