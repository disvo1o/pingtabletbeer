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
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

TOKEN = os.getenv("BOT_TOKEN", "").strip()
TIMEZONE = os.getenv("TIMEZONE", "Europe/Moscow")
DB_PATH = os.getenv("DB_PATH", "/data/bot.db")

DRAW_DAY, DRAW_HOUR, DRAW_MINUTE = 4, 15, 0

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
)
logger = logging.getLogger("pingtablet_beer_bot")


# =========================================================
# ФРАЗЫ ДЛЯ ПРЕДСКАЗАНИЙ
# =========================================================

PREDICTION_PHRASES = [
    "🔮 Шансы есть. Но сначала придётся победить не только соперников, но и судьбу.",
    "🍺 Моё пивное предсказание: всё решится у стола. Ракетку наготове!",
    "Вижу пену… вижу бокал… а дальше туман. Приходи на турнир — проверим 😎",
    "Вероятность успеха повышается на 73%, если не промахиваться по мячу. Научно-почти.",
    "Карты говорят: «Возможно». Ракетка говорит: «Играй!»",
    "🍻 Судьба любит смелых. А Pink Tablet — тех, кто приходит на турнир.",
    "Я бы поставил на тебя пиво, но я бот. Поэтому просто желаю удачи!",
    "Предсказание: больше розыгрышей, меньше сеточных ошибок.",
    "Хрустальный шар показывает… подачу. А вот пиво пока не показывает.",
    "Если фортуна сегодня играет за твою сторону стола — всё возможно.",
    "Мой алгоритм чувствует запах победы. Или это просто пивной бар рядом.",
    "Пиво любит интригу. У тебя есть шанс стать её главным героем.",
    "Звёзды советуют размяться и не спорить с судьёй. Остальное — магия.",
    "Сегодня твой шанс примерно как мяч после сильного топспина: непредсказуем.",
    "Предчувствую эпичный матч. Финал с пеной пока не подтверждён.",
    "Я спросил нейросеть судьбы. Она ответила: «Сыграй ещё один сет».",
    "🍺 Пивной оракул молчит… значит, интрига сохраняется.",
    "Может, да. Может, нет. Но ракетку ты всё равно бери.",
    "Твоя удача уже разминается у стола. Не заставляй её ждать.",
    "Судьба приготовила сюрприз. Надеюсь, он охлаждённый.",
    "Пока что вселенная не дала ответа, зато дала тебе эту подачу.",
    "Шанс есть у каждого. Даже у того, кто держит ракетку как лопату.",
    "Если сегодня попадёшь по мячу чаще, чем по воздуху, это хороший знак.",
    "Пивная комета пролетает раз в неделю. Не пропусти свой розыгрыш!",
    "Мой прогноз: драматичный матч и подозрительно оптимистичные ожидания.",
    "Твоё имя пока не написано на бокале. Но место для него найдётся.",
    "Я бы проверил кофейную гущу, но у нас сегодня пивная тематика.",
    "Удача любит настойчивых. И тех, кто не забывает приходить на турнир.",
    "На горизонте маячит шанс. Возможно, это просто холодильник.",
    "Победа начинается с подачи. Пивная легенда — с пятницы.",
    "Предсказать сложно. Поддержать морально — легко. Вперёд!",
    "Судьба подмигнула мне. Я не понял, тебе или человеку за соседним столом.",
    "Если сегодня будет камбэк, пусть он закончится звоном бокалов.",
    "Шар предсказывает: один из участников точно выиграет. Осталось угадать кто.",
    "Твоя удача просила передать: не забывай следить за мячом.",
    "Вижу три знака: ракетка, сетка и загадочная пена.",
    "Пока прогноз туманный, как запотевшие очки после длинного матча.",
    "Удача уже в чате. Но она пока не раскрывает никнейм.",
    "Возможно, пиво ждёт именно тебя. Но пусть турнир решит честно.",
    "Пивная судьба не любит спойлеры. Приходи и узнай результат.",
    "Сегодня можно выиграть не только очко, но и моё уважение. Пиво — по жеребьёвке.",
    "Я запустил симуляцию тысячи пятниц. Ты хотя бы в одной выглядел уверенно.",
    "Знак свыше: проверь хватку, шнурки и расписание турнира.",
    "Сначала победа над соперником, потом переговоры с холодильником.",
    "Не спрашивай о шансах — создай легенду у теннисного стола.",
    "Ветер удачи дует в твою сторону. Главное, чтобы не сквозняк из бара.",
    "Моё предсказание: ты точно задашь этот вопрос ещё раз.",
    "Я вижу счастливое будущее. Разрешение на выдачу пива пока у организатора.",
    "Судьба бросила монетку и потеряла её под столом. Интрига!",
    "Пока не обещаю пиво, но обещаю случайность и драму.",
]


# =========================================================
# ФРАЗЫ ДЛЯ ТЕХ, КТО НЕ ВЫИГРАЛ
# =========================================================

NOT_WINNER_PHRASES = [
    "Пока нет 🍺 Но не расстраивайся — следующий розыгрыш уже ближе!",
    "Проверил пивной реестр: сегодня твоего имени среди победителей нет. Пока что 😏",
    "Увы, пивной кубок пока не у тебя. Зато шанс будет в следующую пятницу!",
    "Не в этот раз! Но легенды Pink Tablet не сдаются после одного розыгрыша.",
    "Пиво ещё не твоё. Судьба просто выдерживает интригу 🍻",
    "Пивной отдел сообщает: сегодня ты не в списке счастливчиков. Продолжаем борьбу!",
    "Проверка завершена: бокал пока ждёт другого героя.",
    "Сегодня фортуна выбрала другого. Не бери пример с мяча — не отскакивай духом!",
    "Пока без пива, зато с бесценным опытом. Почти равноценно. Почти.",
    "Твоё имя не выпало. Возможно, оно застряло между шариками для пинг-понга.",
    "Увы, розыгрыш прошёл мимо тебя. Но пятницы, как известно, повторяются.",
    "Сегодня приз у другого участника. Твоя пивная арка ещё не завершена.",
    "Нет, но не сдавайся: даже длинный матч состоит из отдельных очков.",
    "Пивная лотерея сегодня не на твоей стороне. Ракетка всё ещё на твоей!",
    "Пока не выиграл. Мой внутренний холодильник выражает сочувствие.",
    "Сегодня победитель другой. Аплодируем ему и готовимся к реваншу!",
    "По базе данных: пиво не назначено. По дружбе: держись 🍺",
    "Не сегодня, чемпион. Но великие камбэки часто начинаются с такого ответа.",
    "Система не обнаружила твоего имени среди победителей. Зато обнаружила боевой настрой.",
    "Пока бокал не твой. Проверь ещё раз после следующего розыгрыша.",
    "Увы! Фортуна сыграла коротко и неудобно. Принимай следующий мяч.",
    "Сегодня приз ушёл другому игроку. Не забудь поздравить победителя!",
    "Нет, но у тебя есть главное — право снова спросить меня в следующую пятницу.",
    "Пивной радар молчит: победителем стал кто-то другой.",
    "Результат отрицательный. Настроение — не обязательно!",
    "Сегодня не ты. Но зато ты точно не проиграл этот диалог.",
    "В этот раз мимо. Даже профессионалы иногда отправляют мяч в сетку.",
    "Бокал получил другой участник. Тебе остаётся тренировать подачу судьбе.",
    "Пока без приза. Попробуй задобрить удачу эффектным топспином.",
    "Нет. Я бы утешил тебя пивом, но я буквально живу в сервере.",
    "Проверил дважды: победитель другой. Проверю в следующий розыгрыш снова!",
    "Не повезло в жеребьёвке — повезёт за столом. Возможно, даже сегодня.",
    "Пока нет. Пивная сага продолжается, следующая серия — в пятницу.",
    "Сегодня у тебя не приз, а сюжетная арка развития персонажа.",
    "Победитель найден, и это не ты. Зато интрига на следующую неделю уже готова.",
    "Не выиграл в этот раз. Но никто не отменял красивую игру и громкий смех.",
    "Сегодня пиво досталось другому. Пусть хотя бы он произнесёт тост за Pink Tablet!",
    "Мой ответ: нет. Моё пожелание: пусть следующий розыгрыш будет твоим!",
    "Случайность выбрала другого человека. Не ругай генератор — он без личных предпочтений.",
    "Нет, зато ты остаёшься в игре. А это уже неплохой сюжетный поворот.",
    "Пивной совет директоров постановил: сегодня приз у другого участника.",
    "Сегодня мимо, но пятничная удача не ушла на пенсию.",
    "Пока твой бокал пуст. Зато календарь обещает новые попытки.",
    "Не ты, увы. Но пусть твои мячи сегодня летят точнее, чем мои прогнозы.",
    "Розыгрыш выбрал другого. Отправь удаче напоминание на следующую пятницу.",
    "Пока нет. Могу предложить только моральную поддержку и виртуальную пену.",
    "Сегодня победитель другой. Не расстраивайся — даже рандом иногда чудит.",
    "Проверка показала: выигрыша пока нет. Пивной детектив закрывает дело до следующего раза.",
    "Не сегодня! Пусть следующий твой выигрыш будет таким же уверенным, как победный удар.",
    "Увы, приз не твой. Но ты всё ещё можешь стать легендой турнира без всякого пива.",
]


# =========================================================
# БАЗА ДАННЫХ
# =========================================================

def db_connect():
    folder = os.path.dirname(DB_PATH)
    if folder:
        os.makedirs(folder, exist_ok=True)

    conn = sqlite3.connect(DB_PATH, timeout=30)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS participants (
            chat_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            username TEXT,
            first_name TEXT,
            last_seen TEXT NOT NULL,
            PRIMARY KEY(chat_id, user_id)
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS winners (
            chat_id INTEGER NOT NULL,
            draw_date TEXT NOT NULL,
            user_id INTEGER NOT NULL,
            username TEXT,
            first_name TEXT,
            PRIMARY KEY(chat_id, draw_date)
        )
    """)

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
        conn.execute(
            """
            INSERT INTO participants
                (chat_id, user_id, username, first_name, last_seen)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(chat_id, user_id) DO UPDATE SET
                username=excluded.username,
                first_name=excluded.first_name,
                last_seen=excluded.last_seen
            """,
            (chat_id, user.id, user.username, user.first_name or "", now),
        )


# =========================================================
# РАСПОЗНАВАНИЕ СООБЩЕНИЙ
# =========================================================

def normalize(text):
    return re.sub(
        r"\s+", " ",
        (text or "").lower().replace("ё", "е")
    ).strip()


def is_beer_question(text):
    t = normalize(text)

    has_beer = any(word in t for word in (
        "пиво", "пива", "пивко", "пивом", "пивной", "пивное"
    ))

    has_win = any(word in t for word in (
        "выигра", "побед", "достан", "получу", "получить", "приз"
    ))

    first_person = any(phrase in t for phrase in (
        "я выигра",
        "я побед",
        "я получ",
        "мне достан",
        "мне выпадет",
        "выиграю ли",
        "выиграл ли я",
        "выиграла ли я",
        "мне пиво",
        "пиво мне",
    ))

    return has_beer and (has_win or first_person or "?" in t)


def asks_about_result(text):
    t = normalize(text)

    markers = (
        "я выиграл",
        "я выиграла",
        "я уже выиграл",
        "я уже выиграла",
        "выиграл ли я",
        "выиграла ли я",
        "мне досталось",
        "я победил",
        "я победила",
        "я получил",
        "я получила",
        "мне выпало",
        "мне достался",
    )

    return any(marker in t for marker in markers)


# =========================================================
# КОМАНДЫ В ЛИЧНЫХ СООБЩЕНИЯХ
# =========================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    chat = update.effective_chat

    if not message or not chat or chat.type != "private":
        return

    await message.reply_text(
        "привет! каждую пятницу в 15:00 по москве "
        "я разыгрываю 1 пиво среди участников группового чата.\n\n"
        "напиши сообщение в группе, чтобы попасть в список участников.\n\n"
        "спроси «когда розыгрыш?» или «я выиграю пиво?» — "
        "и я отвечу.\n\n"
        "команды доступны только в личных сообщениях.\n\n"
        "приз — только для совершеннолетних и при соблюдении местных законов."
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    chat = update.effective_chat

    if not message or not chat or chat.type != "private":
        return

    await message.reply_text(
        "команды работают только в личных сообщениях с ботом.\n"
        "/start — приветствие\n"
        "/beer_status — статус розыгрыша\n"
        "/beer_test — проверка связи"
    )


async def test_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    chat = update.effective_chat

    if not message or not chat or chat.type != "private":
        return

    logger.info("beer_test received in private chat %s", chat.id)
    await message.reply_text(
        "✅ я получаю команды и отвечаю. проверка связи пройдена."
    )


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    chat = update.effective_chat

    if not message or not chat or chat.type != "private":
        return

    with db_session() as conn:
        group_row = conn.execute("""
            SELECT chat_id
            FROM participants
            GROUP BY chat_id
            ORDER BY MAX(last_seen) DESC
            LIMIT 1
        """).fetchone()

        if not group_row:
            await message.reply_text(
                "пока нет участников из групповых чатов."
            )
            return

        group_id = group_row[0]
        today = datetime.now(ZoneInfo(TIMEZONE)).date().isoformat()

        count = conn.execute(
            "SELECT COUNT(*) FROM participants WHERE chat_id=?",
            (group_id,),
        ).fetchone()[0]

        winner = conn.execute(
            """
            SELECT first_name, username
            FROM winners
            WHERE chat_id=? AND draw_date=?
            """,
            (group_id, today),
        ).fetchone()

    reply = (
        f"участников в последней активной группе: {count}\n"
        f"розыгрыш: пятница, 15:00 ({TIMEZONE})."
    )

    if winner:
        name = f"@{winner[1]}" if winner[1] else (
            winner[0] or "победитель"
        )
        reply += f"\nпобедитель сегодня: {name}"

    await message.reply_text(reply.lower())


# =========================================================
# ОТВЕТЫ В ГРУППЕ
# =========================================================

async def answer_beer_questions(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    message = update.effective_message
    chat = update.effective_chat
    user = update.effective_user

    if not message or not chat or not user or user.is_bot:
        return

    if chat.type not in ("group", "supergroup"):
        return

    raw_text = message.text or message.caption or ""
    text = normalize(raw_text)

    if not text:
        return

    # 1. Вопрос о времени розыгрыша
    asks_draw = bool(re.search(
        r"когда\s+(?:будет\s+)?розыгрыш(?:\s+пива)?",
        text,
    ))

    if asks_draw:
        await message.reply_text("узнаем в пятницу в 15:00!")
        return

    # 2. Вопрос о результате прошедшего розыгрыша
    if asks_about_result(text) and is_beer_question(text):
        today = datetime.now(ZoneInfo(TIMEZONE)).date().isoformat()

        with db_session() as conn:
            winner = conn.execute(
                """
                SELECT user_id, username, first_name
                FROM winners
                WHERE chat_id=? AND draw_date=?
                """,
                (chat.id, today),
            ).fetchone()

        if winner is None:
            await message.reply_text(
                "розыгрыш ещё не состоялся или результат пока не записан 🍺"
            )
            return

        if winner[0] == user.id:
            await message.reply_text(
                "да! сегодня пиво достаётся тебе 🍺🎉"
            )
        else:
            phrase = random.choice(NOT_WINNER_PHRASES)
            await message.reply_text(phrase.lower())

        return

    # 3. Вопрос о шансах выиграть в будущем
    if is_beer_question(text) and not asks_about_result(text):
        phrase = random.choice(PREDICTION_PHRASES)
        await message.reply_text(phrase.lower())


# =========================================================
# УЧЁТ УЧАСТНИКОВ
# =========================================================

async def track_messages(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    chat = update.effective_chat
    user = update.effective_user

    if chat and chat.type in ("group", "supergroup") and user:
        record_participant(chat.id, user)


# =========================================================
# ПЯТНИЧНЫЙ РОЗЫГРЫШ
# =========================================================

def next_draw(now):
    target = now.replace(
        hour=DRAW_HOUR,
        minute=DRAW_MINUTE,
        second=0,
        microsecond=0,
    )

    target += timedelta(days=(DRAW_DAY - now.weekday()) % 7)

    if target <= now:
        target += timedelta(days=7)

    return target


async def draw_loop(app: Application):
    tz = ZoneInfo(TIMEZONE)

    while True:
        now = datetime.now(tz)
        target = next_draw(now)

        logger.info(
            "Next draw at %s (%s)",
            target.isoformat(),
            TIMEZONE,
        )

        await asyncio.sleep(
            max(1, (target - now).total_seconds())
        )

        draw_date = datetime.now(tz).date().isoformat()

        with db_session() as conn:
            chats = conn.execute(
                "SELECT DISTINCT chat_id FROM participants"
            ).fetchall()

        for (chat_id,) in chats:
            try:
                with db_session() as conn:
                    existing = conn.execute(
                        """
                        SELECT 1 FROM winners
                        WHERE chat_id=? AND draw_date=?
                        """,
                        (chat_id, draw_date),
                    ).fetchone()

                    if existing:
                        continue

                    people = conn.execute(
                        """
                        SELECT user_id, username, first_name
                        FROM participants
                        WHERE chat_id=?
                        """,
                        (chat_id,),
                    ).fetchall()

                    if not people:
                        logger.warning(
                            "No participants in chat %s",
                            chat_id,
                        )
                        continue

                    winner = random.choice(people)

                    conn.execute(
                        """
                        INSERT OR IGNORE INTO winners
                            (chat_id, draw_date, user_id, username, first_name)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (
                            chat_id,
                            draw_date,
                            winner[0],
                            winner[1],
                            winner[2],
                        ),
                    )

                mention = (
                    f"@{winner[1]}"
                    if winner[1]
                    else (winner[2] or "победитель")
                )

                await app.bot.send_message(
                    chat_id=chat_id,
                    text=(
                        "🍺 пятничный розыгрыш!\n\n"
                        "сегодня 1 пиво на любом турнире "
                        f"ping tablet получает: {mention} 🎉\n\n"
                        "покажи это сообщение организатору турнира, "
                        "чтобы получить приз. только для совершеннолетних "
                        "и при соблюдении местных законов и правил площадки."
                    ).lower(),
                )

            except Exception:
                logger.exception(
                    "Failed to draw/send winner for chat %s",
                    chat_id,
                )


async def post_init(app: Application):
    app.bot_data["draw_task"] = asyncio.create_task(
        draw_loop(app),
        name="friday-beer-draw",
    )


async def post_shutdown(app: Application):
    task = app.bot_data.get("draw_task")

    if task and not task.done():
        task.cancel()

        try:
            await task
        except asyncio.CancelledError:
            pass


# =========================================================
# ЗАПУСК
# =========================================================

def main():
    if not TOKEN:
        raise RuntimeError(
            "Не задан BOT_TOKEN. Добавь токен в переменные Railway."
        )

    db_connect().close()

    app = (
        Application.builder()
        .token(TOKEN)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("beer_help", help_command))
    app.add_handler(CommandHandler("beer_status", status))
    app.add_handler(CommandHandler("beer_test", test_command))

    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            answer_beer_questions,
        ),
        group=0,
    )

    app.add_handler(
        MessageHandler(
            filters.ALL & ~filters.COMMAND,
            track_messages,
        ),
        group=1,
    )

    logger.info(
        "Starting bot. Timezone: %s; database: %s",
        TIMEZONE,
        DB_PATH,
    )

    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
