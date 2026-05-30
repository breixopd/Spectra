#!/bin/sh
set -e

# Read secrets from Docker Swarm secret files
CH_PASS=$(cat /run/secrets/clickhouse_password 2>/dev/null || echo '')
export TENSORZERO_CLICKHOUSE_URL="http://default:${CH_PASS}@clickhouse:8123/tensorzero"
export OPENAI_API_KEY=$(cat /run/secrets/openai_api_key 2>/dev/null || echo "${OPENAI_API_KEY:-}")
export ANTHROPIC_API_KEY=$(cat /run/secrets/anthropic_api_key 2>/dev/null || echo "${ANTHROPIC_API_KEY:-}")

# Clear password variable
unset CH_PASS

exec gateway --config-file /app/config/tensorzero.toml
