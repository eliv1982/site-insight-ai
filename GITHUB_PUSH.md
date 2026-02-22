# Отправка проекта в GitHub

**Репозиторий:** https://github.com/eliv1982/Vibe-coding-final-project

---

## Шаг 1. Открыть PowerShell и перейти в проект

Введите **одну** команду:

```
cd "C:\Users\eshle\Cursor projects\Vibe coding projects\Final project"
```

---

## Шаг 2. Привязать репозиторий (remote)

Проверить, есть ли уже `origin`:

```
git remote -v
```

**Если вывода нет** — добавить:

```
git remote add origin https://github.com/eliv1982/Vibe-coding-final-project.git
```

**Если `origin` уже есть** (другой URL) — заменить:

```
git remote set-url origin https://github.com/eliv1982/Vibe-coding-final-project.git
```

---

## Шаг 3. Добавить все файлы

```
git add .
```

Проверить список (не должно быть `.env` и `node_modules`):

```
git status
```

---

## Шаг 4. Сделать коммит

```
git commit -m "Full project: backend, frontend, deploy, docs"
```

Если появится «nothing to commit» — все изменения уже закоммичены, переходите к шагу 5.

---

## Шаг 5. Отправить на GitHub

Если основная ветка **main**:

```
git push -u origin main
```

Если основная ветка **master**:

```
git push -u origin master
```

Если Git напишет, что ветка на GitHub называется по-другому (например `main`), выполните ту команду, которую он предложит в сообщении об ошибке.

---

## Если просят логин и пароль

- **Username:** ваш логин GitHub (например `eliv1982`).
- **Password:** не пароль от аккаунта, а **Personal Access Token**.  
  Создать: GitHub → ваш профиль (правый верх) → **Settings** → **Developer settings** → **Personal access tokens** → **Generate new token (classic)** → отметить **repo** → сгенерировать и скопировать токен. Вставить его в поле пароля.

---

## Кратко: все команды подряд

```
cd "C:\Users\eshle\Cursor projects\Vibe coding projects\Final project"
git remote set-url origin https://github.com/eliv1982/Vibe-coding-final-project.git
git add .
git status
git commit -m "Full project: backend, frontend, deploy, docs"
git push -u origin main
```

(Если ветка `master` — в последней команде замените `main` на `master`.)
