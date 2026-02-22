#!/usr/bin/env bash
# =============================================================================
# Первый деплой или перезапуск приложения на сервере (образы с Docker Hub)
# Запуск: ./deploy.sh
# Использует docker-compose.deploy.yml (pull + up -d).
# =============================================================================

set -e

# Каталог проекта (где лежит docker-compose.deploy.yml)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_DIR="${DEPLOY_DIR:-$SCRIPT_DIR}"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.deploy.yml}"

cd "$DEPLOY_DIR"
if [[ ! -f "$COMPOSE_FILE" ]]; then
  echo "Ошибка: файл $COMPOSE_FILE не найден в $DEPLOY_DIR"
  exit 1
fi

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Деплой: каталог $DEPLOY_DIR"
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Загрузка образов с Docker Hub..."
docker compose -f "$COMPOSE_FILE" pull
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Запуск контейнеров в фоне..."
docker compose -f "$COMPOSE_FILE" up -d
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Готово."
docker compose -f "$COMPOSE_FILE" ps
