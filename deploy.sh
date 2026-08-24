#!/usr/bin/env bash

set -Eeuo pipefail

readonly SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
readonly COMPOSE_FILE="$SCRIPT_DIR/docker-compose.deploy.yml"
readonly ENV_FILE="$SCRIPT_DIR/.env"

fail() {
  printf 'Deployment error: %s\n' "$1" >&2
  exit 1
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || fail "required command not found: $1"
}

require_command git
require_command docker
docker compose version >/dev/null 2>&1 || fail "Docker Compose v2 is required"

[[ -f "$COMPOSE_FILE" ]] || fail "missing Compose file: $COMPOSE_FILE"
[[ -f "$ENV_FILE" ]] || fail "missing backend environment file: $ENV_FILE"

cd -- "$SCRIPT_DIR"
git rev-parse --is-inside-work-tree >/dev/null 2>&1 || fail "deployment directory is not a Git worktree"

proxy_network="${PROXY_NETWORK:-}"
[[ -n "$proxy_network" ]] || fail "PROXY_NETWORK is required"
[[ ${#proxy_network} -le 255 && "$proxy_network" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]*$ ]] \
  || fail "PROXY_NETWORK contains unsupported characters"

image_tag="${IMAGE_TAG:-}"
if [[ -z "$image_tag" ]]; then
  image_tag="$(git rev-parse --short=12 HEAD)"
fi
[[ ${#image_tag} -le 128 && "$image_tag" =~ ^[A-Za-z0-9_][A-Za-z0-9_.-]*$ ]] \
  || fail "IMAGE_TAG is not a valid Docker image tag"

[[ -z "$(git status --porcelain --untracked-files=normal)" ]] \
  || fail "working tree is dirty; commit or stash changes before deployment"

docker network inspect "$proxy_network" >/dev/null 2>&1 \
  || fail "external proxy network does not exist: $proxy_network"

export IMAGE_TAG="$image_tag"
export PROXY_NETWORK="$proxy_network"
export BACKEND_ENV_FILE="$ENV_FILE"

printf 'Deploying Site Insight AI image tag %s\n' "$IMAGE_TAG"
docker compose -f "$COMPOSE_FILE" build
docker compose -f "$COMPOSE_FILE" up -d --wait
docker compose -f "$COMPOSE_FILE" ps
