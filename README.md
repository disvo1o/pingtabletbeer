# ping tablet friday beer bot

Set the `BOT_TOKEN` environment variable in Railway. Optional variables: `TIMEZONE=Europe/Moscow`, `DB_PATH=/data/bot.db`, `LOG_LEVEL=INFO`.

The bot replies in group chats only to questions like “Когда розыгрыш?” and “Я выиграл пиво?” with the lowercase phrase `узнаем в пятницу в 15:00!`. Commands only respond in private chats. The weekly draw is scheduled for Friday at 15:00 Moscow time.

Important: run only one active deployment using this bot token. If an older Railway service is still running with the same token, it can continue sending old replies.
