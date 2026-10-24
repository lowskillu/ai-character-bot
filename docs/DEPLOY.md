# Деплой

Чеклист перед первым выкатом на публичный сервер и то, что нужно знать про
эксплуатацию.

## 1. Секреты

```bash
cp .env.example .env
python -c "import secrets; print(secrets.token_urlsafe(48))"   # WEBHOOK_SECRET
python -c "import secrets; print(secrets.token_urlsafe(32))"   # REDIS_PASSWORD
```

| Переменная | Без неё |
|---|---|
| `BOT_TOKEN` | нечем работать |
| `WEBHOOK_SECRET` | **бот не стартует.** Любой, кто узнал URL вебхука, шлёт апдейты от имени любого user_id — включая админский, а это `/admin` → рассылка всей базе и `/addpremium` |
| `REDIS_PASSWORD` | `--requirepass ""` → Redis без пароля. Порт на loopback, но FSM-состояния и счётчики квот открыты всему, что есть на хосте |
| `POSTGRES_PASSWORD` | — |
| `OPENROUTER_API_KEY`, `RUNWARE_API_KEY` | чат и фото не работают |

`ALLOW_INSECURE_WEBHOOK=true` снимает проверку секрета. Это только для локальной
разработки; в проде — никогда.

`.env` в `.gitignore` и в `.dockerignore`, в образ не попадает. Проверить, что
он действительно не отслеживается:

```bash
git ls-files | grep -c '^\.env$'
```

Должно быть `0`.

## 2. Домен вебхука

`WEBHOOK_HOST` сейчас указывает на quick-туннель `trycloudflare.com`. Такой
туннель эфемерный: имя хоста меняется при каждом перезапуске, и после этого
Telegram шлёт апдейты в никуда. Перед боевым запуском нужен постоянный домен
(именованный Cloudflare-туннель или A-запись + TLS).

## 3. Что закрыто и почему

Публично доступен **только** `POST /webhook`.

`nginx/default.conf` ограничивает приватными подсетями:

* проксирование на локальный Bot API сервер (`location /`) — он запущен с
  `--allow-unauthorized-updates`;
* раздачу скачанных файлов (`location /file/bot<token>/…`).

Боту это через nginx не нужно: он ходит в `telegram-api-server:8081` напрямую по
compose-сети (`TELEGRAM_API_BASE`).

Аутентификация `/webhook` — это secret token, а не список IP: запросы приходят
от Cloudflare, а не из диапазонов Telegram, так что allowlist здесь либо сломал
бы доставку, либо был бы настолько широким, что ничего не доказывает.

Порты Postgres и Redis замаплены на `127.0.0.1`.

После запуска проверить конфиг nginx (в этой сессии контейнером не
валидировался — Docker daemon был выключен):

```bash
docker compose exec nginx nginx -t
```

## 4. Запуск

```bash
docker compose up -d --build
```

Порядок гарантирован через `depends_on`: Postgres и Redis по healthcheck →
одноразовый job `migrations` (`alembic upgrade head`) должен выйти с 0 → бот →
nginx ждёт `/healthz` бота.

Проверка:

```bash
docker compose ps
docker compose exec tg_bot python -c "import urllib.request;print(urllib.request.urlopen('http://127.0.0.1:80/healthz').read())"
```

## 5. Ёмкость

Замеры — в [LOAD_TEST.md](LOAD_TEST.md).

| Переменная | По умолчанию | Когда трогать |
|---|---|---|
| `DB_POOL_SIZE` / `DB_MAX_OVERFLOW` | 30 / 20 | `db_pool_checked_out` в `/metrics` подходит к `db_pool_size`. Это первое, что упирается при волне регистраций |
| `LLM_CONCURRENCY` | 256 | растёт `requests_shed_total`, а OpenRouter держит |
| `IMAGE_CONCURRENCY` | 8 | только если поднят лимит на стороне Runware |
| `FREE_MESSAGE_LIMIT` / `PREMIUM_MESSAGE_LIMIT` | 25 / 200 | продуктовое решение |

## 5.1 Модели

Все id и параметры сэмплинга — в env, значения по умолчанию совпадают с тем,
что было зашито в коде. Полный список в `.env.example`.

| Переменная | По умолчанию | Что это |
|---|---|---|
| `CHAT_MODEL` | `meta-llama/llama-3.3-70b-instruct` | чат с персонажем, OpenRouter |
| `PROMPT_MODEL` | `meta-llama/llama-3.3-70b-instruct` | сборка описания картинки, OpenRouter |
| `IMAGE_MODEL_ANIME` | `runware:101@1` | модель Runware, она же фолбэк |
| `IMAGE_MODEL_REALISTIC` | `runware:101@1` | модель Runware |
| `MAX_HISTORY_LENGTH` | 5 | сколько прошлых реплик уходит в модель. В БД хранится 10 — это отдельная ручка: поднять улучшает связность и стоит токенов |

Смена модели теперь не требует пересборки образа: правите `.env` и
`docker compose up -d`. Откатить неудачную модель — так же.

**На одно фото уходит два платных вызова** (OpenRouter на промпт + Runware на
картинку), на одно сообщение в чате — один.

`max_connections` у Postgres поднят до 200, чтобы пул можно было увеличивать.

## 6. Что НЕ проверено — проверить на первом выкате

Тесты (237) не поднимают ни Postgres, ни Redis, ни Telegram: всё внешнее
заменено фейками. Поэтому следующее проверено только чтением и компиляцией
запроса, но ни разу не выполнялось против настоящей базы:

| Что | Где | Как проверить |
|---|---|---|
| Обрезка истории одним `DELETE … NOT IN (SELECT … LIMIT)` | `services/dialog_history.py:trim_profile_history` | Написать 15 сообщений в один профиль, убедиться, что осталось 10 и это самые новые |
| Keyset-пагинация рассылки | `database/orm.py:iter_all` | `/admin` → рассылка на базе из >500 юзеров; убедиться, что дошло до всех, а не до первых 500 |
| Конфиг nginx | `nginx/default.conf` | `docker compose exec nginx nginx -t` |
| Сборка образа | `Dockerfile` | `docker compose build` |

Стенд для первых двух уже описан в [LOAD_TEST.md](LOAD_TEST.md) — там поднимается
настоящий Postgres в докере.

## 7. Что осталось нерешённым

Это не сделано намеренно — нужны ваши решения, а не мои догадки.

**Бэкапы Postgres.** Их нет. Нужно выбрать место хранения, расписание и срок
хранения. Минимум:

```bash
docker compose exec -T postgres_db pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB" | gzip > backup-$(date +%F).sql.gz
```

**Лимиты ресурсов в compose.** Не выставлены: не зная размера сервера, любое
значение — это риск словить OOM-kill вместо защиты.

**Ретеншен истории.** `delete_old_profile_messages()` (45 дней) написана, но
нигде не вызывается. Таблица и так ограничена 10 строками на профиль
(`trim_profile_history`), так что она нужна не для размера, а как политика
хранения: сейчас переписка неактивного пользователя лежит вечно. Это стоит
решить осознанно.

**Мёртвые объекты схемы.** Колонка `users.welcome_sent` (нигде не читается).
Удаление — необратимая миграция, поэтому оставлена на ваше решение.

**Ротация ключей.** `.env` в git не попадал, но если сервер или файл когда-либо
были доступны кому-то ещё — `BOT_TOKEN`, `OPENROUTER_API_KEY` и
`RUNWARE_API_KEY` стоит перевыпустить.

**Путь генерации фото под нагрузкой не тестировался.** Нужен стаб Runware.
`IMAGE_CONCURRENCY=8` взят из головы, под реальные лимиты Runware не подбирался.
