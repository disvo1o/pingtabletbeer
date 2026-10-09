import asyncio
import logging
import os
import random
import sqlite3
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

TOKEN = os.environ["BOT_TOKEN"]
TIMEZONE = os.getenv("TIMEZONE", "Europe/Moscow")
DRAW_DAY = 4  # Monday=0, Friday=4
DRAW_HOUR = 15
DRAW_MINUTE = 0
DB_PATH = os.getenv("DB_PATH", "/data/bot.db")

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


def db_connect():
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS participants (
            chat_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            username TEXT,
            first_name TEXT,
            last_seen TEXT NOT NULL,
            PRIMARY KEY (chat_id, user_id)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS winners (
            chat_id INTEGER NOT NULL,
            draw_date TEXT NOT NULL,
            user_id INTEGER NOT NULL,
            username TEXT,
            first_name TEXT,
            PRIMARY KEY (chat_id, draw_date)
        )
    """)
    conn.commit()
    return conn


def record_participant(chat_id, user):
    if user is None or user.is_bot:
        return
    now = datetime.now(ZoneInfo(TIMEZONE)).isoformat()
    with db_connect() as conn:
        conn.execute("""
            INSERT INTO participants(chat_id, user_id, username, first_name, last_seen)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(chat_id, user_id) DO UPDATE SET
                username=excluded.username,
                first_name=excluded.first_name,
                last_seen=excluded.last_seen
        """, (chat_id, user.id, user.username, user.first_name or "", now))


async def track_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat and update.effective_chat.type in ("group", "supergroup"):
        record_participant(update.effective_chat.id, update.effective_user)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(
        "Привет! Я каждую пятницу в 15:00 по московскому времени разыгрываю "
        "1 пиво среди участников этого чата.\n\n"
        "Чтобы попасть в список, напиши любое сообщение в чате после добавления бота. "
        "Не учитываю ботов. Участие и получение приза — только для совершеннолетних "
        "и с соблюдением местных законов.\n\n"
        "Команды: /beer_status — статус розыгрыша; /beer_help — инструкция."
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(
        "Как участвовать:\n"
        "1. Добавьте меня в групповой чат.\n"
        "2. В BotFather отключите Privacy Mode командой /setprivacy → выберите бота → Disable.\n"
        "3. После этого участники должны написать хотя бы одно сообщение в чате, "
        "чтобы попасть в список.\n"
        "4. Каждый пятничный розыгрыш выбирает одного случайного участника из тех, "
        "кто писал в чате.\n\n"
        "Важно: бот не может прочитать сообщения, отправленные до того, как он был добавлен. "
        "Участники, удалившие бота или заблокировавшие его, могут оставаться в списке. "
        "Администратор может перезапустить/остановить бота на Railway."
    )


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if not chat or chat.type not in ("group", "supergroup"):
        await update.effective_message.reply_text("Эту команду нужно вызвать в групповом чате.")
        return
    with db_connect() as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM participants WHERE chat_id=?", (chat.id,)
        ).fetchone()[0]
        today = datetime.now(ZoneInfo(TIMEZONE)).date().isoformat()
        winner = conn.execute(
            "SELECT first_name, username FROM winners WHERE chat_id=? AND draw_date=?",
            (chat.id, today),
        ).fetchone()
    text = f"Участников в списке: {count}\nРозыгрыш: каждую пятницу в 15:00 ({TIMEZONE})."
    if winner:
        label = f"@{winner[1]}" if winner[1] else winner[0]
        text += f"\nПобедитель сегодня: {label}"
    await update.effective_message.reply_text(text)


def next_draw(now):
    target = now.replace(hour=DRAW_HOUR, minute=DRAW_MINUTE, second=0, microsecond=0)
    days_ahead = (DRAW_DAY - now.weekday()) % 7
    target += timedelta(days=days_ahead)
    if target <= now:
        target += timedelta(days=7)
    return target


async def draw_loop(app: Application):
    tz = ZoneInfo(TIMEZONE)
    while True:
        now = datetime.now(tz)
        target = next_draw(now)
        delay = max(1, (target - now).total_seconds())
        logger.info("Next draw at %s (%s)", target.isoformat(), TIMEZONE)
        await asyncio.sleep(delay)

        draw_date = datetime.now(tz).date().isoformat()
        with db_connect() as conn:
            chats = conn.execute(
                "SELECT DISTINCT chat_id FROM participants"
            ).fetchall()

        for (chat_id,) in chats:
            try:
                with db_connect() as conn:
                    already = conn.execute(
                        "SELECT 1 FROM winners WHERE chat_id=? AND draw_date=?",
                        (chat_id, draw_date),
                    ).fetchone()
                    if already:
                        continue
                    people = conn.execute(
                        "SELECT user_id, username, first_name FROM participants WHERE chat_id=?",
                        (chat_id,),
                    ).fetchall()
                    if not people:
                        continue
                    winner = random.choice(people)
                    conn.execute(
                        "INSERT OR IGNORE INTO winners(chat_id, draw_date, user_id, username, first_name) "
                        "VALUES (?, ?, ?, ?, ?)",
                        (chat_id, draw_date, winner[0], winner[1], winner[2]),
                    )
                    conn.commit()

                user_id, username, first_name = winner
                mention = f"@{username}" if username else (first_name or "Победитель")
                await app.bot.send_message(
                    chat_id=chat_id,
                    text=(
                        f"🍺 ПЯТНИЧНЫЙ РОЗЫГРЫШ!\n\n"
                        f"Сегодня 1 пиво на любом турнире Pink Tablet получает: {mention} 🎉\n\n"
                        f"Покажи это сообщение организатору турнира, чтобы получить приз. "
                        f"Приз предназначен только для совершеннолетних; получение зависит "
                        f"от правил площадки и местного законодательства."
                    ),
                )
            except Exception:
                logger.exception("Failed to draw/send winner for chat %s", chat_id)


async def post_init(app: Application):
    app.create_task(draw_loop(app))


def main():
    # Create DB/schema before starting polling.
    db_connect().close()
    app = Application.builder().token(TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("beer_help", help_command))
    app.add_handler(CommandHandler("beer_status", status))
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, track_messages))
    logger.info("Bot started. Timezone: %s; database: %s", TIMEZONE, DB_PATH)
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
