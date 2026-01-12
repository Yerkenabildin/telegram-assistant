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

### 3. Создать файл .env

```bash
cp .env.example .env
```

Откройте `.env` и заполните:

```env
API_ID=12345678
API_HASH=your_api_hash_here
PERSONAL_TG_LOGIN=your_username
WORK_TG_LOGIN=your_work_username
```

### 4. Запустить

```bash
docker-compose up -d
```

### 5. Авторизоваться

1. Откройте в браузере: http://localhost:5050
2. Введите номер телефона
3. Введите код из Telegram
4. При наличии 2FA — введите пароль

Готово!

## Использование

### Настройка автоответа

Отправьте команду со своего рабочего аккаунта (`WORK_TG_LOGIN`) в ответ на сообщение-шаблон:

```
/set_for [emoji]
```

Где `[emoji]` — это кастомный emoji-статус, при котором будет отправляться этот ответ.

### Как работает автоответ

1. Бот проверяет ваш текущий emoji-статус
2. Если для этого emoji настроен шаблон — отправляет автоответ
3. Ограничение: не чаще 1 раза в 30 минут одному пользователю
4. Если статус = `AVAILABLE_EMOJI_ID` — автоответы отключены

### ASAP-уведомления

Когда кто-то пишет сообщение со словом "ASAP", вы получите уведомление на личный аккаунт (`PERSONAL_TG_LOGIN`).

## Переменные окружения

| Переменная | Обязательная | Описание |
|------------|--------------|----------|
| `API_ID` | Да | API ID из my.telegram.org |
| `API_HASH` | Да | API Hash из my.telegram.org |
| `PERSONAL_TG_LOGIN` | Да | Username для ASAP-уведомлений |
| `WORK_TG_LOGIN` | Да | Username с правами настройки автоответов |
| `AVAILABLE_EMOJI_ID` | Нет | ID emoji-статуса "доступен" (автоответы отключены) |
| `SECRET_KEY` | Нет | Ключ шифрования сессии (генерируется автоматически) |
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
