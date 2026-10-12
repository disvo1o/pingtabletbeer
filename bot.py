    text = normalize(raw_text)
    if not text:
        return

    # Handle small wording variations, punctuation, and mentions in the same message.
    asks_draw = bool(re.search(r"когда\s+(?:будет\s+)?розыгрыш(?:\s+пива)?", text))
    asks_won = bool(re.search(
        r"\bя\s+(?:уже\s+)?выиграл(?:а)?\s+(?:это\s+)?пиво\b", text
    ))

    if asks_draw or asks_won:
        logger.info("Fixed beer answer matched chat_id=%s user_id=%s", chat.id, user.id)
        await message.reply_text("узнаем в пятницу в 15:00!")


async def track_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    if chat and chat.type in ("group", "supergroup") and user:
        record_participant(chat.id, user)


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
                    existing = conn.execute(
                        "SELECT 1 FROM winners WHERE chat_id=? AND draw_date=?", (chat_id, draw_date)
                    ).fetchone()
                    if existing:
                        continue
                    people = conn.execute(
                        "SELECT user_id,username,first_name FROM participants WHERE chat_id=?", (chat_id,)
                    ).fetchall()
                    if not people:
                        logger.warning("No participants in chat %s; skipping draw", chat_id)
                        continue
                    winner = random.choice(people)
                    conn.execute(
                        "INSERT OR IGNORE INTO winners(chat_id,draw_date,user_id,username,first_name) VALUES(?,?,?,?,?)",
                        (chat_id, draw_date, winner[0], winner[1], winner[2]),
                    )
                mention = f"@{winner[1]}" if winner[1] else (winner[2] or "Победитель")
                await app.bot.send_message(
                    chat_id=chat_id,
                    text=(
                        f"🍺 пятничный розыгрыш!\n\nсегодня 1 пиво на любом турнире pink tablet получает: "
                        f"{mention} 🎉\n\nпокажи это сообщение организатору турнира, чтобы получить приз. "
                        "только для совершеннолетних и при соблюдении местных законов и правил площадки."
                    ).lower(),
                )
            except Exception:
                logger.exception("Failed to draw/send winner for chat %s", chat_id)


async def post_init(app: Application):
    # Use asyncio.create_task here so PTB doesn't warn that Application.create_task
    # was called before the application started polling.
    app.bot_data["draw_task"] = asyncio.create_task(draw_loop(app), name="friday-beer-draw")


async def post_shutdown(app: Application):
    task = app.bot_data.get("draw_task")
    if task and not task.done():
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


def main():
    if not TOKEN:
        raise RuntimeError("Не задан BOT_TOKEN. Добавь токен бота в переменные окружения Railway.")
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
    # Handler is intentionally not restricted to mentions: the target question works as plain text too.
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, answer_beer_questions), group=0)
    # Track any ordinary group activity in a separate handler group.
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, track_messages), group=1)
    logger.info("Starting bot. Timezone: %s; database: %s", TIMEZONE, DB_PATH)
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
