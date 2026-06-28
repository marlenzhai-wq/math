import logging
import random
import json
import os
import asyncio
import time

from telegram import Update
from telegram.ext import Application, MessageHandler, CommandHandler, filters, ContextTypes
from telegram.error import TimedOut, NetworkError, RetryAfter

BOT_TOKEN = os.getenv("BOT_TOKEN")
DATA_FILE = "game_data.json"

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', 
    level=logging.INFO # DEBUG деңгейіне өзгерттік
)
logger = logging.getLogger(__name__)

# Хабарлама санауышы файлдан өшіп қалмауы үшін жедел жадта сақтаймыз
CHAT_LOCKS = {}

def load_data():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, 'r', encoding='utf-8') as f:
                content = f.read().strip()
                if not content:
                    return {}
                return json.loads(content)
        except Exception as e:
            logger.error(f"Файлды оқуда қате: {e}")
            return {}
    return {}

def save_data(data):
    try:
        with open(DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        logger.error(f"Файлды сақтауда қате: {e}")
        return False

def generate_math():
    operation = random.choice(["+", "-", "*", "÷"])

    if operation == "+":
        a = random.randint(100, 10000)
        b = random.randint(100, 10000)
        return f"{a} + {b} = ?", a + b

    elif operation == "-":
        a = random.randint(100, 10000)
        b = random.randint(100, a)
        return f"{a} - {b} = ?", a - b

    elif operation == "*":
        a = random.randint(10, 200)
        b = random.randint(10, 100)
        return f"{a} × {b} = ?", a * b

    else:
        b = random.randint(2, 100)
        answer = random.randint(2, 200)
        a = b * answer
        return f"{a} ÷ {b} = ?", answer

async def top_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not update.effective_chat or update.effective_chat.type not in ["group", "supergroup"]:
            return
        
        chat_id = str(update.effective_chat.id)
        data = load_data()
        
        if chat_id not in data or not data[chat_id].get("players"):
            await update.message.reply_text("📊 *Әлі ешкім ұпай жинаған жоқ!*", parse_mode="Markdown")
            return
            
        players = data[chat_id]["players"]
        sorted_players = sorted(players.items(), key=lambda x: x[1].get("score", 0), reverse=True)
        
        leaderboard = "🏆 *ТОП-10 ҮЗДІК ОЙЫНШЫ* 🏆\n\n"
        top_10 = sorted_players[:10]
        
        for idx, (user_id, user_data) in enumerate(top_10, 1):
            name = user_data.get("name", "Аноним")
            score = user_data.get("score", 0)
            medal = "🥇" if idx == 1 else "🥈" if idx == 2 else "🥉" if idx == 3 else "📌"
            leaderboard += f"{medal} {idx}. *{name}* — {score} ұпай\n"
            
        leaderboard += f"\n📊 *Жалпы ойыншылар саны:* {len(players)}"
        await update.message.reply_text(leaderboard, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"top қатесі: {e}")

async def score_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not update.effective_chat or update.effective_chat.type not in ["group", "supergroup"]:
            return
            
        chat_id = str(update.effective_chat.id)
        user_id = str(update.effective_user.id)
        user_name = update.effective_user.first_name or update.effective_user.username or "Аноним"
        
        data = load_data()
        if chat_id not in data or user_id not in data[chat_id].get("players", {}):
            await update.message.reply_text(f"📊 *{user_name}*, сізде әлі ұпай жоқ.", parse_mode="Markdown")
            return
            
        score = data[chat_id]["players"][user_id].get("score", 0)
        await update.message.reply_text(f"📊 *{user_name}*!\n\n🏅 Сіздің ұпайыңыз: *{score}*", parse_mode="Markdown")
    except Exception as e:
        logger.error(f"score қатесі: {e}")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        logger.debug(f"📩 Хабарлама келді: {update.message.text if update.message else 'None'}")
        
        if not update.effective_chat or update.effective_chat.type not in ["group", "supergroup"]:
            logger.debug(f"Чат түрі: {update.effective_chat.type if update.effective_chat else 'None'} - Өткізіп жіберілді")
            return
            
        if update.effective_user and update.effective_user.is_bot:
            logger.debug("Боттың хабарламасы - өткізіп жіберілді")
            return
            
        if not update.message or not update.message.text:
            logger.debug("Хабарлама мәтіні жоқ - өткізіп жіберілді")
            return
        
        chat_id = str(update.effective_chat.id)
        if chat_id not in CHAT_LOCKS:
            CHAT_LOCKS[chat_id] = asyncio.Lock()
        user_name = update.effective_user.first_name or "Аноним"
        message_text = update.message.text.strip()
        
        logger.debug(f"📝 Чат {chat_id}, Пайдаланушы: {user_name}, Мәтін: {message_text}")
        
        data = load_data()
        
        if chat_id not in data:
            logger.info(f"🆕 Жаңа чат: {chat_id}")
            data[chat_id] = {
                "active": False,
                "question": None,
                "players": {},
                "interval": 10,
                "reminder_counter": 0,
                "question_message_id": None,
                "counter": 0,
                "question_time": 0
            }
            save_data(data)
        
       
        chat_data = data[chat_id]
        if (
            chat_data.get("active")
            and time.time() - chat_data.get("question_time", 0) > 300
        ):
            chat_data["active"] = False
            chat_data["question"] = None
            chat_data["question_time"] = 0
        
        logger.debug(f"📊 Чат деректері: active={chat_data.get('active')}, counter={COUNTERS[chat_id]}, interval={chat_data.get('interval', 10)}")
        
        # 1. Белсенді сұрақ болса, жауапты тексеру
        if chat_data.get("active") and chat_data.get("question"):
            logger.debug("🔍 Белсенді сұрақ бар, жауапты тексереміз")
            user_id = str(update.effective_user.id)
            try:
                user_answer = int(message_text)
                correct_answer = chat_data["question"]["answer"]
                logger.debug(f"🔢 Жауап: {user_answer}, Дұрыс: {correct_answer}")
                
                async with CHAT_LOCKS[chat_id]:

                    if not chat_data.get("active"):
                        return

                    if user_answer == correct_answer:
                        logger.info(f"✅ Дұрыс жауап! {user_name} +1 ұпай")

                        if "players" not in chat_data:
                            chat_data["players"] = {}

                        if user_id not in chat_data["players"]:
                            chat_data["players"][user_id] = {
                                "name": user_name,
                                "score": 0
                            }

                        chat_data["players"][user_id]["name"] = user_name
                        chat_data["players"][user_id]["score"] += 1
                    
                    
                    
                    if "players" not in chat_data:
                        chat_data["players"] = {}
                        
                    if user_id not in chat_data["players"]:
                        chat_data["players"][user_id] = {"name": user_name, "score": 0}
                    
                    chat_data["players"][user_id]["name"] = user_name
                    chat_data["players"][user_id]["score"] += 1
                    new_score = chat_data["players"][user_id]["score"]
                    
                    await update.message.reply_text(
                        f"🎉 *{user_name}* 🎉\n\n✅ *ДҰРЫС ЖАУАП!*\n📝 Жауап: `{correct_answer}`\n🏆 +1 ұпай!\n📊 Жалпы ұпайыңыз: *{new_score}*",
                        parse_mode="Markdown"
                    )
                    
                    chat_data["active"] = False
                    chat_data["question"] = None
                    chat_data["reminder_counter"] = 0
                    save_data(data)
                    return
            except ValueError:
                logger.debug(f"❌ Сан емес: {message_text}")
                pass
        
        # 2. Сұрақ жоқ кезде хабарламаларды санау
        if not chat_data.get("active"):
            chat_data["counter"] += 1

            interval = chat_data.get("interval", 10)
            logger.info(
                f"🔢 Чат [{chat_id}]: Санауыш {chat_data['counter']}/{interval}"
            )

            if chat_data["counter"] >= interval:
                logger.info("🎯 Интервалға жетті! Жаңа есеп шығарылады")

                q_text, q_ans = generate_math()

                chat_data["question"] = {
                    "question": q_text,
                    "answer": q_ans
                }

                chat_data["active"] = True
                chat_data["question_time"] = time.time()
                chat_data["reminder_counter"] = 0
                chat_data["counter"] = 0
                
                if chat_data.get("question_message_id"):
                    try:
                        await context.bot.delete_message(
                            chat_id=chat_id,
                            message_id=chat_data["question_message_id"]
                        )
                        logger.debug("🗑️ Ескі хабарлама өшірілді")
                    except Exception as e:
                        logger.error(f"Ескі хабарламаны өшіру қатесі: {e}")
                    chat_data["question_message_id"] = None
                
                msg = await update.message.reply_text(
                    f"🧮 *МАТЕМАТИКАЛЫҚ ЕСЕП!* 🧮\n\n"
                    f"❓ *{q_text}*\n\n"
                    f"⚡ *БІРІНШІ* болып дұрыс жауап жазған адам *1 ұпай* алады!\n"
                    f"💡 Тек қана санды жазыңыз.",
                    parse_mode="Markdown"
                )
                
                chat_data["question_message_id"] = msg.message_id
                save_data(data)
                logger.info(f"✅ Жаңа есеп жіберілді: {q_text}")
            else:
                logger.debug(f"⏳ Әлі интервалға жетпеді: {COUNTERS[chat_id]}/{interval}")
        else:
            logger.debug("⏸️ Сұрақ белсенді, санауыш өткізіп жіберілді")
                
    except Exception as e:
        logger.error(f"handle_message қатесі: {e}", exc_info=True)

async def set_interval_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not update.effective_chat or update.effective_chat.type not in ["group", "supergroup"]:
            return

        chat_id = str(update.effective_chat.id)
        user_id = update.effective_user.id

        if not context.args:
            await update.message.reply_text("📌 Қолдану: /setinterval 10")
            return

        try:
            new_interval = int(context.args[0])
            if new_interval < 1:
                raise ValueError
        except ValueError:
            await update.message.reply_text("❌ Дұрыс сан енгіз!")
            return

        member = await context.bot.get_chat_member(chat_id, user_id)
        if member.status not in ["administrator", "creator"]:
            await update.message.reply_text("⛔ Бұл команданы тек админ қолдана алады!")
            return

        data = load_data()

        if chat_id not in data:
            data[chat_id] = {
                "active": False, 
                "question": None, 
                "players": {}, 
                "interval": 10,
                "reminder_counter": 0,
                "question_message_id": None
            }

        data[chat_id]["interval"] = new_interval
        save_data(data)

        await update.message.reply_text(f"✅ Есеп шығу интервалы өзгертілді: {new_interval} хабарлама сайын")

    except Exception as e:
        logger.error(f"set_interval қатесі: {e}")

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    try:
        if isinstance(context.error, TimedOut):
            return
        elif isinstance(context.error, NetworkError):
            return
        elif isinstance(context.error, RetryAfter):
            await asyncio.sleep(context.error.retry_after)
            return
        else:
            logger.error(f"Өңделмеген қате: {context.error}")
    except Exception as e:
        logger.error(f"Қате өңдегіштегі жаңа қате: {e}")

def main():
    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .connect_timeout(30.0)
        .read_timeout(30.0)
        .write_timeout(30.0)
        .pool_timeout(30.0)
        .build()
    )
    
    app.add_error_handler(error_handler)
    
    app.add_handler(CommandHandler("top", top_command))
    app.add_handler(CommandHandler("score", score_command))
    app.add_handler(CommandHandler("setinterval", set_interval_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    logger.info("🤖 Бот сәтті іске қосылды!")
    
    app.run_polling(
        drop_pending_updates=True,
        allowed_updates=["message"],
        poll_interval=0.5,
        timeout=30
    )

if __name__ == "__main__":
    main()
