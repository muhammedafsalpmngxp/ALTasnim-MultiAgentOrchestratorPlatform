#!/bin/sh
# Generates backend/conf/service_conf.yaml from RAGFlow's own official template
# (backend/docker/service_conf.yaml.template), substituting the container-network hostnames
# set as environment variables in docker-compose.
#
# IMPORTANT: this does NOT use `envsubst`. envsubst only does literal $VAR/${VAR} text
# replacement — it has no concept of the "${VAR:-default}" fallback syntax used throughout the
# template (that's POSIX shell parameter expansion, a shell feature, not something an external
# text tool implements). Since "ES_HOST:-es01" isn't a real variable name, envsubst left every
# placeholder as unresolved literal garbage text (e.g. the literal string "${ES_HOST:-es01}"
# ended up IN the generated config), which is why Elasticsearch/MySQL/Redis/MinIO all failed to
# connect — every host string was broken, not just misconfigured.
#
# The shell itself DOES understand "${VAR:-default}" natively, so we let `sh` perform the
# substitution directly via a heredoc + eval, which forces the shell to expand every
# "${VAR:-default}" occurrence using its own real parameter-expansion rules.
set -e

TEMPLATE="/app/backend/docker/service_conf.yaml.template"
TARGET="/app/backend/conf/service_conf.yaml"

if [ -f "$TEMPLATE" ]; then
  mkdir -p "$(dirname "$TARGET")"
  eval "cat <<SERVICE_CONF_EOF
$(cat "$TEMPLATE")
SERVICE_CONF_EOF" > "$TARGET"
fi

exec "$@"
