# Telegram Proxy Search

Ищет рабочие MTProto-прокси из Telegram-канала [@ProxyMTProto](https://t.me/ProxyMTProto) и проверяет их.

## Как это работает

Процесс разделён на два этапа:

1. **С VPN** — парсится канал, собираются кандидаты
2. **Без VPN** — каждый прокси проверяется подключением с вашего IP

Такая проверка работает, потому что за вас тестирует подключение к прокси.

Поддерживаются все типы секретов: `ee` (fake-TLS), `dd` (randomized), plain, в любой кодировке (hex, base64url).

## Установка

Нужен Python 3.13+ и [uv](https://github.com/astral-sh/uv).

```bash
git clone https://github.com/leo-proger/tg-proxy-search.git
cd tg-proxy-search
uv sync
```

## Настройка (опционально)

### Авторизация сессии (делается один раз)

По умолчанию используются встроенные ключи Telegram Desktop — дополнительная регистрация не нужна.

Если хотите использовать собственные ключи (нет ограничений по частоте запросов), зайдите на [my.telegram.org](https://my.telegram.org), создайте приложение и добавьте в `.env`:

```bash
cp .env.example .env
# раскомментируйте API_ID и API_HASH в .env
```

Авторизуйте сессию:

```bash
uv run python -c "
from telethon.sync import TelegramClient
from dotenv import load_dotenv; import os; load_dotenv()
api_id = int(os.environ.get('API_ID', 2040))
api_hash = os.environ.get('API_HASH', 'b18441a1ff607e10a989891a5462e627')
with TelegramClient('telethon', api_id, api_hash) as c:
    c.start(); print('Готово')
"
```

После этого появится файл `telethon.session` — он нужен для работы.

## Запуск

```bash
uv run python main.py
```

### Режимы

```
1  Найти N рабочих прокси
   Парсит канал и проверяет прокси, пока не наберёт N рабочих.

2  Взять все прокси за последние X часов
   Парсит посты за указанный промежуток и проверяет все найденные.

3  Перепроверить рабочие из кэша  (VPN не нужен)
   Берёт ранее найденные рабочие прокси и проверяет их заново —
   быстро, без парсинга канала.
```

### Пример сессии

```
Выберите режим:
  1  Найти N рабочих прокси
  2  Взять все прокси за последние X часов
  3  Перепроверить рабочие из кэша (VPN не нужен)

Режим [1/2/3]: 1
Сколько рабочих прокси найти? 3

── Шаг 1: парсится канал
  Включите VPN и нажмите Enter...

  Парсится @ProxyMTProto

  Кандидатов найдено: 87  (просмотрено 200 постов)

──────────────────────────────────────────────────────
Выключите VPN и нажмите Enter для начала проверки...

── Шаг 2: проверяется
  ✓ flux.proxytop.space:443
  ✗ office.proxytg.live:443
  ✗ surge.linkflowhub.shop:443
  ✓ last.nolags.pw:443
  ✓ jet.proxytop.space:443

  Рабочих: 3  (проверено 5/87)

── Результат

  tg://proxy?server=flux.proxytop.space&port=443&secret=...
  tg://proxy?server=last.nolags.pw&port=443&secret=...
  tg://proxy?server=jet.proxytop.space&port=443&secret=...
```

## Настройки .env

| Переменная | По умолчанию | Описание |
|---|---|---|
| `API_ID` | Telegram Desktop | Личный API ID с my.telegram.org (опционально) |
| `API_HASH` | Telegram Desktop | Личный API Hash с my.telegram.org (опционально) |
| `TCP_TIMEOUT` | `15` | Таймаут проверки одного прокси в секундах (опционально) |
| `PROXY_CHECK_CONCURRENCY` | `8` | Сколько прокси проверять параллельно (опционально) |
| `MAX_SCAN_MESSAGES` | `1000` | Лимит постов за один запуск парсинга (опционально) |
| `PROXY_WORKING_RECHECK_HOURS` | `48` | Через сколько часов перепроверять рабочий прокси (опционально) |
| `PROXY_FAILED_RECHECK_HOURS` | `24` | Через сколько часов перепроверять нерабочий прокси (опционально) |
| `AUTO_ADD_TO_TELEGRAM` | `false` | Открывать ссылки в Telegram Desktop автоматически (опционально) |

## Диагностика

Если прокси выглядит рабочим в Telegram, но программа его не видит — запустите:

```bash
uv run python diagnose.py "tg://proxy?server=...&port=...&secret=..."
```

Покажет каждый шаг подключения и сырые байты ответа сервера. Запускать **без VPN**.
