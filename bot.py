import asyncio
import logging
import os
import random
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

TOKEN = os.environ["BOT_TOKEN"]
TIMEZONE = os.getenv("TIMEZONE", "Europe/Moscow")
DB_PATH = os.getenv("DB_PATH", "/data/bot.db")
DRAW_DAY, DRAW_HOUR, DRAW_MINUTE = 4, 15, 0  # Friday, 15:00

logging.basicConfig(format="%(asctime)s | %(levelname)s | %(name)s | %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)


def db_connect():
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""CREATE TABLE IF NOT EXISTS participants (
        chat_id INTEGER NOT NULL, user_id INTEGER NOT NULL, username TEXT,
        first_name TEXT, last_seen TEXT NOT NULL, PRIMARY KEY(chat_id, user_id))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS winners (
        chat_id INTEGER NOT NULL, draw_date TEXT NOT NULL, user_id INTEGER NOT NULL,
        username TEXT, first_name TEXT, PRIMARY KEY(chat_id, draw_date))""")
    conn.commit()
    return conn


@contextmanager
def db_session():
    conn = db_connect()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def record_participant(chat_id, user):
    if user is None or user.is_bot:
        return
    now = datetime.now(ZoneInfo(TIMEZONE)).isoformat()
    with db_session() as conn:
        conn.execute("""INSERT INTO participants(chat_id,user_id,username,first_name,last_seen)
            VALUES(?,?,?,?,?) ON CONFLICT(chat_id,user_id) DO UPDATE SET
            username=excluded.username, first_name=excluded.first_name, last_seen=excluded.last_seen""",
            (chat_id, user.id, user.username, user.first_name or "", now))


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(
        "Привет! Каждую пятницу в 15:00 по московскому времени я разыгрываю 1 пиво "
        "среди участников этого чата. Напиши сообщение в чате, чтобы попасть в список.\n"
        "Команды: /beer_status — статус; /beer_help — инструкция.\n"
        "Приз — только для совершеннолетних и с соблюдением местных законов."
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(
        "Добавьте бота в групповой чат и отключите Privacy Mode через @BotFather: "
        "/setprivacy → выбрать бота → Disable. Участник попадает в список после первого "
        "сообщения, отправленного после добавления бота. Бот не может собрать старые сообщения."
    )


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if not chat or chat.type not in ("group", "supergroup"):
        await update.effective_message.reply_text("Вызови эту команду в групповом чате.")
        return
    today = datetime.now(ZoneInfo(TIMEZONE)).date().isoformat()
    with db_session() as conn:
        count = conn.execute("SELECT COUNT(*) FROM participants WHERE chat_id=?", (chat.id,)).fetchone()[0]
        winner = conn.execute("SELECT first_name,username FROM winners WHERE chat_id=? AND draw_date=?",
                              (chat.id, today)).fetchone()
    reply = f"Участников в списке: {count}\nРозыгрыш: пятница, 15:00 ({TIMEZONE})."
    if winner:
        reply += "\nПобедитель сегодня: " + (f"@{winner[1]}" if winner[1] else winner[0])
    await update.effective_message.reply_text(reply)


PREDICTION_PHRASES = [
    '🔮 Шансы есть. Но сначала придётся победить не только соперников, но и судьбу.',
    '🍺 Моё пивное предсказание: всё решится у стола. Ракетку наготове!',
    'Вижу пену… вижу бокал… а дальше туман. Приходи на турнир — проверим 😎',
    'Вероятность успеха повышается на 73%, если не промахиваться по мячу. Научно-почти.',
    'Карты говорят: «Возможно». Ракетка говорит: «Играй!»',
    '🍻 Судьба любит смелых. А Pink Tablet — тех, кто приходит на турнир.',
    'Я бы поставил на тебя пиво, но я бот. Поэтому просто желаю удачи!',
    'Предсказание: больше розыгрышей, меньше сеточных ошибок.',
    'Хрустальный шар показывает… подачу. А вот пиво пока не показывает.',
    'Если фортуна сегодня играет за твою сторону стола — всё возможно.',
    'Мой алгоритм чувствует запах победы. Или это просто пивной бар рядом.',
    'Пиво любит интригу. У тебя есть шанс стать её главным героем.',
    'Звёзды советуют размяться и не спорить с судьёй. Остальное — магия.',
    'Сегодня твой шанс примерно как мяч после сильного топспина: непредсказуем.',
    'Предчувствую эпичный матч. Финал с пеной пока не подтверждён.',
    'Я спросил нейросеть судьбы. Она ответила: «Сыграй ещё один сет».',
    '🍺 Пивной оракул молчит… значит, интрига сохраняется.',
    'Может, да. Может, нет. Но ракетку ты всё равно бери.',
    'Твоя удача уже разминается у стола. Не заставляй её ждать.',
    'Судьба приготовила сюрприз. Надеюсь, он охлаждённый.',
    'Пока что вселенная не дала ответа, зато дала тебе эту подачу.',
    'Шанс есть у каждого. Даже у того, кто держит ракетку как лопату.',
    'Если сегодня попадёшь по мячу чаще, чем по воздуху, это хороший знак.',
    'Пивная комета пролетает раз в неделю. Не пропусти свой розыгрыш!',
    'Мой прогноз: драматичный матч и подозрительно оптимистичные ожидания.',
    'Твоё имя пока не написано на бокале. Но место для него найдётся.',
    'Я бы проверил кофейную гущу, но у нас сегодня пивная тематика.',
    'Удача любит настойчивых. И тех, кто не забывает записываться на турнир.',
    'На горизонте маячит шанс. Возможно, это просто холодильник.',
    'Победа начинается с подачи. Пивная легенда — с пятницы.',
    'Предсказать сложно. Поддержать морально — легко. Вперёд!',
    'Судьба подмигнула мне. Я не понял, тебе или человеку за соседним столом.',
    'Если сегодня будет камбэк, пусть он закончится звоном бокалов.',
    'Шар предсказывает: один из участников точно выиграет. Осталось угадать кто.',
    'Твоя удача просила передать: не забывай следить за мячом.',
    'Вижу три знака: ракетка, сетка и загадочная пена.',
    'Пока прогноз туманный, как запотевшие очки после длинного матча.',
    'Удача уже в чате. Но она пока не раскрывает никнейм.',
    'Возможно, пиво ждёт именно тебя. Но пусть турнир решит честно.',
    'Пивная судьба не любит спойлеры. Приходи и узнай результат.',
    'Сегодня можно выиграть не только очко, но и моё уважение. Пиво — по жеребьёвке.',
    'Я запустил симуляцию тысячи пятниц. Ты хотя бы в одной выглядел уверенно.',
    'Знак свыше: проверь хватку, шнурки и расписание турнира.',
    'Сначала победа над соперником, потом переговоры с холодильником.',
    'Не спрашивай о шансах — создай легенду у теннисного стола.',
    'Ветер удачи дует в твою сторону. Главное, чтобы не сквозняк из бара.',
    'Моё предсказание: ты точно задашь этот вопрос ещё раз.',
    'Я вижу счастливое будущее. Разрешение на выдачу пива пока у организатора.',
    'Судьба бросила монетку и потеряла её под столом. Интрига!',
    'Пока не обещаю пиво, но обещаю случайность и драму.',
]
NOT_WINNER_PHRASES = [
    'Пока нет 🍺 Но не расстраивайся — следующий розыгрыш уже ближе!',
    'Проверил пивной реестр: сегодня твоего имени среди победителей нет. Пока что 😏',
    'Увы, пивной кубок пока не у тебя. Зато шанс будет в следующую пятницу!',
    'Не в этот раз! Но легенды Pink Tablet не сдаются после одного розыгрыша.',
    'Пиво ещё не твоё. Судьба просто выдерживает интригу 🍻',
    'Пивной отдел сообщает: сегодня ты не в списке счастливчиков. Продолжаем борьбу!',
    'Проверка завершена: бокал пока ждёт другого героя.',
    'Сегодня фортуна выбрала другого. Не бери пример с мяча — не отскакивай духом!',
    'Пока без пива, зато с бесценным опытом. Почти равноценно. Почти.',
    'Твоё имя не выпало. Возможно, оно застряло между шариками для пинг-понга.',
    'Увы, розыгрыш прошёл мимо тебя. Но пятницы, как известно, повторяются.',
    'Сегодня приз у другого участника. Твоя пивная арка ещё не завершена.',
    'Нет, но не сдавайся: даже длинный матч состоит из отдельных очков.',
    'Пивная лотерея сегодня не на твоей стороне. Ракетка всё ещё на твоей!',
    'Пока не выиграл. Мой внутренний холодильник выражает сочувствие.',
    'Сегодня победитель другой. Аплодируем ему и готовимся к реваншу!',
    'По базе данных: пиво не назначено. По дружбе: держись 🍺',
    'Не сегодня, чемпион. Но великие камбэки часто начинаются с такого ответа.',
    'Система не обнаружила твоего имени среди победителей. Зато обнаружила боевой настрой.',
    'Пока бокал не твой. Проверь ещё раз после следующего розыгрыша.',
    'Увы! Фортуна сыграла коротко и неудобно. Принимай следующий мяч.',
    'Сегодня приз ушёл другому игроку. Не забудь поздравить победителя!',
    'Нет, но у тебя есть главное — право снова спросить меня в следующую пятницу.',
    'Пивной радар молчит: победителем стал кто-то другой.',
    'Результат отрицательный. Настроение — не обязательно!',
    'Сегодня не ты. Но зато ты точно не проиграл этот диалог.',
    'В этот раз мимо. Даже профессионалы иногда отправляют мяч в сетку.',
    'Бокал получил другой участник. Тебе остаётся тренировать подачу судьбе.',
    'Пока без приза. Попробуй задобрить удачу эффектным топспином.',
    'Нет. Я бы утешил тебя пивом, но я буквально живу в сервере.',
    'Проверил дважды: победитель другой. Проверю в следующий розыгрыш снова!',
    'Не повезло в жеребьёвке — повезёт за столом. Возможно, даже сегодня.',
    'Пока нет. Пивная сага продолжается, следующая серия — в пятницу.',
    'Сегодня у тебя не приз, а сюжетная арка развития персонажа.',
    'Победитель найден, и это не ты. Зато интрига на следующую неделю уже готова.',
    'Не выиграл в этот раз. Но никто не отменял красивую игру и громкий смех.',
    'Сегодня пиво досталось другому. Пусть хотя бы он произнесёт тост за Pink Tablet!',
    'Мой ответ: нет. Моё пожелание: пусть следующий розыгрыш будет твоим!',
    'Случайность выбрала другого человека. Не ругай генератор — он без личных предпочтений.',
    'Нет, зато ты остаёшься в игре. А это уже неплохой сюжетный поворот.',
    'Пивной совет директоров постановил: сегодня приз у другого участника.',
    'Сегодня мимо, но пятничная удача не ушла на пенсию.',
    'Пока твой бокал пуст. Зато календарь обещает новые попытки.',
    'Не ты, увы. Но пусть твои мячи сегодня летят точнее, чем мои прогнозы.',
    'Розыгрыш выбрал другого. Отправь удаче напоминание на следующую пятницу.',
    'Пока нет. Могу предложить только моральную поддержку и виртуальную пену.',
    'Сегодня победитель другой. Не расстраивайся — даже рандом иногда чудит.',
    'Проверка показала: выигрыша пока нет. Пивной детектив закрывает дело до следующего раза.',
    'Не сегодня! Пусть следующий твой выигрыш будет таким же уверенным, как победный удар.',
    'Увы, приз не твой. Но ты всё ещё можешь стать легендой турнира без всякого пива.',
]


async def answer_mention_questions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message, chat, user = update.effective_message, update.effective_chat, update.effective_user
    if not message or not chat or not user or chat.type not in ("group", "supergroup"):
        return
    text = message.text or ""
    if not text:
        return

    username = context.bot_data.get("bot_username")
    if username is None:
        me = await context.bot.get_me()
        username = me.username or ""
        context.bot_data["bot_username"] = username
    mentioned = bool(username and re.search(rf"(?i)(?<!\w)@{re.escape(username)}(?!\w)", text))
    for entity in message.entities or []:
        if entity.type == "text_mention" and entity.user and entity.user.id == context.bot.id:
            mentioned = True
    if not mentioned:
        return

    normalized = text.lower().replace("ё", "е")
    if "пив" not in normalized or not ("?" in normalized or any(x in normalized for x in ("выигра", "получ", "достан"))):
        return

    asks_past = any(x in normalized for x in (
        "я выиграл", "я выиграла", "я уже выиграл", "я уже выиграла",
        "выиграл ли я", "выиграла ли я", "мне досталось", "я победил", "я победила"
    ))
    if not asks_past:
        await message.reply_text(random.choice(PREDICTION_PHRASES))
        return

    today = datetime.now(ZoneInfo(TIMEZONE)).date().isoformat()
    with db_session() as conn:
        today_winner = conn.execute("SELECT user_id FROM winners WHERE chat_id=? AND draw_date=?",
                                    (chat.id, today)).fetchone()
        latest = conn.execute("SELECT draw_date,user_id FROM winners WHERE chat_id=? ORDER BY draw_date DESC LIMIT 1",
                              (chat.id,)).fetchone()
    if today_winner and today_winner[0] == user.id:
        reply = "🍺 ДА! Сегодня ты победитель розыгрыша Pink Tablet. Покажи это сообщение организатору турнира и уточни получение приза. Только для совершеннолетних."
    elif latest and latest[1] == user.id:
        reply = f"🍺 Да! Ты выиграл в розыгрыше {latest[0]}. Покажи сообщение организатору и уточни получение приза."
    elif today_winner:
        reply = random.choice(NOT_WINNER_PHRASES)
    else:
        reply = "⏳ Результат сегодняшнего розыгрыша ещё не записан. Если розыгрыш уже должен был пройти, проверь, что бот был включён в 15:00."
    await message.reply_text(reply)


async def track_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat and update.effective_chat.type in ("group", "supergroup"):
        record_participant(update.effective_chat.id, update.effective_user)


def next_draw(now):
    target = now.replace(hour=DRAW_HOUR, minute=DRAW_MINUTE, second=0, microsecond=0)
    target += timedelta(days=(DRAW_DAY - now.weekday()) % 7)
    if target <= now:
        target += timedelta(days=7)
    return target


async def draw_loop(app: Application):
    tz = ZoneInfo(TIMEZONE)
    while True:
        now = datetime.now(tz)
        target = next_draw(now)
        logger.info("Next draw at %s (%s)", target.isoformat(), TIMEZONE)
        await asyncio.sleep(max(1, (target - now).total_seconds()))
        draw_date = datetime.now(tz).date().isoformat()
        with db_session() as conn:
            chats = conn.execute("SELECT DISTINCT chat_id FROM participants").fetchall()
        for (chat_id,) in chats:
            try:
                with db_session() as conn:
                    if conn.execute("SELECT 1 FROM winners WHERE chat_id=? AND draw_date=?",
                                    (chat_id, draw_date)).fetchone():
                        continue
                    people = conn.execute("SELECT user_id,username,first_name FROM participants WHERE chat_id=?",
                                          (chat_id,)).fetchall()
                    if not people:
                        continue
                    winner = random.choice(people)
                    conn.execute("INSERT OR IGNORE INTO winners(chat_id,draw_date,user_id,username,first_name) VALUES(?,?,?,?,?)",
                                 (chat_id, draw_date, winner[0], winner[1], winner[2]))
                mention = f"@{winner[1]}" if winner[1] else (winner[2] or "Победитель")
                await app.bot.send_message(chat_id=chat_id, text=(
                    f"🍺 ПЯТНИЧНЫЙ РОЗЫГРЫШ!\n\nСегодня 1 пиво на любом турнире Pink Tablet получает: {mention} 🎉\n\n"
                    "Покажи это сообщение организатору турнира, чтобы получить приз. Только для совершеннолетних "
                    "и при соблюдении местных законов и правил площадки."
                ))
            except Exception:
                logger.exception("Failed to draw/send winner for chat %s", chat_id)


async def post_init(app: Application):
    app.create_task(draw_loop(app))


def main():
    db_connect().close()
    app = Application.builder().token(TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("beer_help", help_command))
    app.add_handler(CommandHandler("beer_status", status))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, answer_mention_questions), group=0)
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, track_messages), group=1)
    logger.info("Bot started. Timezone: %s; database: %s", TIMEZONE, DB_PATH)
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
