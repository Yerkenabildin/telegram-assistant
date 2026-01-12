# Telegram Auto-Responder Bot

Telegram бот для автоматических ответов на личные сообщения в зависимости от вашего emoji-статуса.

## Возможности

- Автоответы на личные сообщения на основе emoji-статуса
- Шаблоны сообщений привязаны к конкретным emoji
- Уведомления при обнаружении слова "ASAP" в сообщениях
- Веб-интерфейс для авторизации в Telegram
- Поддержка Docker

## Быстрый старт

### 1. Скачать файлы

```bash
mkdir telegram-assistant && cd telegram-assistant
curl -O https://raw.githubusercontent.com/yerkebulan/telegram-assistant/main/docker-compose.yaml
curl -O https://raw.githubusercontent.com/yerkebulan/telegram-assistant/main/.env.example
```

### 2. Получить API ключи Telegram

1. Перейдите на [my.telegram.org](https://my.telegram.org)
2. Войдите в свой аккаунт
3. Перейдите в "API development tools"
4. Создайте приложение и скопируйте `API_ID` и `API_HASH`

### 3. Создать Telegram бота

1. Откройте [@BotFather](https://t.me/BotFather) в Telegram
2. Отправьте `/newbot`
3. Введите имя и username для бота
4. Скопируйте полученный токен

### 4. Создать файл .env

```bash
cp .env.example .env
```

Откройте `.env` и заполните:

```env
API_ID=12345678
API_HASH=your_api_hash_here
BOT_TOKEN=123456:ABC-DEF...
PERSONAL_TG_LOGIN=your_username
```

### 5. Запустить

```bash
docker-compose up -d
```

### 6. Авторизоваться

1. Откройте вашего бота в Telegram
2. Отправьте `/start`
3. Следуйте инструкциям для авторизации

Готово!

## Использование

### Как работает автоответ

1. Бот проверяет ваш текущий emoji-статус
2. Если для этого emoji настроен шаблон — отправляет автоответ
3. Ограничение: не чаще 1 раза в 30 минут одному пользователю
4. Если статус = `AVAILABLE_EMOJI_ID` — автоответы отключены

### ASAP-уведомления

Когда кто-то пишет сообщение со словом "ASAP", вы получите уведомление на личный аккаунт (`PERSONAL_TG_LOGIN`).

Дополнительно можно настроить webhook — при ASAP-сообщениях будет отправляться POST-запрос:

```bash
ASAP_WEBHOOK_URL=https://your-server.com/webhook
```

Формат запроса:
```json
{
  "sender": "@username или ID",
  "message": "текст сообщения"
}
```

## Переменные окружения

| Переменная | Обязательная | Описание |
|------------|--------------|----------|
| `API_ID` | Да | API ID из my.telegram.org |
| `API_HASH` | Да | API Hash из my.telegram.org |
| `BOT_TOKEN` | Да | Токен бота от @BotFather |
| `PERSONAL_TG_LOGIN` | Да | Username для ASAP-уведомлений |
| `AVAILABLE_EMOJI_ID` | Нет | ID emoji-статуса "доступен" (автоответы отключены) |
| `ALLOWED_USERNAME` | Нет | Разрешить авторизацию только этому username |
| `ASAP_WEBHOOK_URL` | Нет | URL для отправки webhook при ASAP-сообщениях |
| `DOCKER_IMAGE` | Нет | Кастомный Docker образ |
| `STORAGE_PATH` | Нет | Путь к папке хранения данных |

## Для разработчиков

```bash
git clone https://github.com/yerkebulan/telegram-assistant.git
cd telegram-assistant
cp .env.example .env
# заполнить .env
pip install -r requirements.txt
python main.py
```

## Лицензия

MIT
