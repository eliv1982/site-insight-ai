#!/usr/bin/env bash
# =============================================================================
# Скрипт автоматического обновления контейнеров из Docker Hub
# Запуск: ./update-containers.sh
# Для cron: 0 * * * * /полный/путь/к/update-containers.sh >> /var/log/update-containers.log 2>&1
# =============================================================================

set -e

# -----------------------------------------------------------------------------
# Настройки (меняйте под свой сервер и образы)
# -----------------------------------------------------------------------------
# Каталог, где лежит docker-compose.deploy.yml (обычно корень проекта)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_DIR="${DEPLOY_DIR:-$SCRIPT_DIR}"

# Файл docker-compose для деплоя (можно заменить на свой путь)
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.deploy.yml}"

# Docker Hub: ник и теги образов (при смене ника правьте здесь и в docker-compose.deploy.yml)
DOCKER_HUB_NICK="${DOCKER_HUB_NICK:-eliv1982}"
BACKEND_IMAGE="${DOCKER_HUB_NICK}/backend:latest"
FRONTEND_IMAGE="${DOCKER_HUB_NICK}/frontend:latest"

# Имена контейнеров (должны совпадать с container_name в docker-compose)
BACKEND_CONTAINER="backend"
FRONTEND_CONTAINER="frontend"

# -----------------------------------------------------------------------------
# Шаг 1: Переход в каталог деплоя и проверка наличия compose-файла
# -----------------------------------------------------------------------------
cd "$DEPLOY_DIR"
if [[ ! -f "$COMPOSE_FILE" ]]; then
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] Ошибка: файл $COMPOSE_FILE не найден в $DEPLOY_DIR"
  exit 1
fi

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Каталог деплоя: $DEPLOY_DIR"
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Compose-файл: $COMPOSE_FILE"

# -----------------------------------------------------------------------------
# Шаг 2: Сохранить текущие образы, используемые контейнерами (для лога)
# -----------------------------------------------------------------------------
backend_old=""
frontend_old=""
if docker inspect "$BACKEND_CONTAINER" --format '{{.Image}}' 2>/dev/null | grep -q .; then
  backend_old=$(docker inspect "$BACKEND_CONTAINER" --format '{{.Image}}' 2>/dev/null || true)
fi
if docker inspect "$FRONTEND_CONTAINER" --format '{{.Image}}' 2>/dev/null | grep -q .; then
  frontend_old=$(docker inspect "$FRONTEND_CONTAINER" --format '{{.Image}}' 2>/dev/null || true)
fi

# -----------------------------------------------------------------------------
# Шаг 3: Скачать последние образы с Docker Hub
# -----------------------------------------------------------------------------
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Проверка и загрузка образов: $BACKEND_IMAGE, $FRONTEND_IMAGE"
docker compose -f "$COMPOSE_FILE" pull

# -----------------------------------------------------------------------------
# Шаг 4: Узнать ID образов после pull (для сравнения)
# -----------------------------------------------------------------------------
backend_new=$(docker image inspect "$BACKEND_IMAGE" --format '{{.Id}}' 2>/dev/null || echo "")
frontend_new=$(docker image inspect "$FRONTEND_IMAGE" --format '{{.Id}}' 2>/dev/null || echo "")

if [[ -z "$backend_new" ]]; then
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] Ошибка: образ $BACKEND_IMAGE не найден после pull"
  exit 1
fi
if [[ -z "$frontend_new" ]]; then
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] Ошибка: образ $FRONTEND_IMAGE не найден после pull"
  exit 1
fi

# -----------------------------------------------------------------------------
# Шаг 5: Определить, какие сервисы изменились
# -----------------------------------------------------------------------------
backend_updated=false
frontend_updated=false
if [[ -n "$backend_old" && "$backend_old" != "$backend_new" ]]; then
  backend_updated=true
fi
if [[ -z "$backend_old" ]]; then
  backend_updated=true
fi
if [[ -n "$frontend_old" && "$frontend_old" != "$frontend_new" ]]; then
  frontend_updated=true
fi
if [[ -z "$frontend_old" ]]; then
  frontend_updated=true
fi

# -----------------------------------------------------------------------------
# Шаг 6: Лог — какие контейнеры обновлены, какие без изменений
# -----------------------------------------------------------------------------
if "$backend_updated"; then
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] Backend: обновлён (образ $BACKEND_IMAGE)"
else
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] Backend: без изменений"
fi
if "$frontend_updated"; then
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] Frontend: обновлён (образ $FRONTEND_IMAGE)"
else
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] Frontend: без изменений"
fi

# -----------------------------------------------------------------------------
# Шаг 7: Если есть обновления — перезапустить контейнеры
# -----------------------------------------------------------------------------
if "$backend_updated" || "$frontend_updated"; then
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] Остановка текущих контейнеров и запуск новых версий..."
  docker compose -f "$COMPOSE_FILE" down
  docker compose -f "$COMPOSE_FILE" up -d
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] Готово. Контейнеры запущены в фоне (docker-compose up -d)."
else
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] Все образы актуальны, перезапуск не выполнен."
fi
