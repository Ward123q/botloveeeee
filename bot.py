import asyncio
import json
import os
import random
from datetime import datetime

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton
from aiogram.enums import ParseMode
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiohttp import web

from config import *
import texts as msg


# ============================================================
# БАЗА ДАННЫХ
# ============================================================
def load_db():
    try:
        if not os.path.exists(DB_FILE):
            initial = {
                "users": [],
                "stats": {},
                "letters": [],      # отложенные письма
                "thoughts": [],     # о чём думаю
                "moments": [],      # любимые моменты
                "secrets": [],      # секретки
                "past_letters": [], # письма от прошлого
                "warm_used": [],    # использованные тёплые
            }
            with open(DB_FILE, "w", encoding="utf-8") as f:
                json.dump(initial, f, ensure_ascii=False, indent=2)
            print(f"📁 Создан файл БД: {DB_FILE}")
            return initial

        with open(DB_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            # миграция старых БД
            for key in ["letters", "thoughts", "moments", "secrets", "past_letters", "warm_used"]:
                if key not in data:
                    data[key] = []
            return data

    except Exception as e:
        print(f"⚠️ Ошибка загрузки БД: {e}")
        return {
            "users": [], "stats": {}, "letters": [], "thoughts": [],
            "moments": [], "secrets": [], "past_letters": [], "warm_used": [],
        }


def save_db(data):
    try:
        with open(DB_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"⚠️ Ошибка сохранения БД: {e}")


def register_user(user_id):
    try:
        db = load_db()
        if user_id not in db["users"]:
            db["users"].append(user_id)
            save_db(db)
            print(f"✅ Новый пользователь: {user_id}")
    except Exception as e:
        print(f"⚠️ {e}")


def add_stat(user_id, key):
    try:
        db = load_db()
        stats = db.get("stats", {})
        user_stats = stats.get(str(user_id), {})
        user_stats[key] = user_stats.get(key, 0) + 1
        stats[str(user_id)] = user_stats
        db["stats"] = stats
        save_db(db)
    except Exception as e:
        print(f"⚠️ stat: {e}")


def get_random_warm():
    """Возвращает случайное тёплое сообщение, стараясь не повторять"""
    try:
        db = load_db()
        used = db.get("warm_used", [])
        all_warm = msg.WARM

        # если использовано больше 80% — сбрасываем
        if len(used) >= len(all_warm) * 0.8:
            used = []

        available = [w for w in all_warm if w not in used]
        if not available:
            available = all_warm
            used = []

        choice = random.choice(available)
        used.append(choice)
        db["warm_used"] = used
        save_db(db)
        return choice
    except Exception:
        return random.choice(msg.WARM)


# ============================================================
# УТИЛИТЫ
# ============================================================
def days_together():
    start = datetime.strptime(START_DATE, "%Y-%m-%d %H:%M")
    return (datetime.now() - start).days


def hours_together():
    start = datetime.strptime(START_DATE, "%Y-%m-%d %H:%M")
    return int((datetime.now() - start).total_seconds() // 3600)


def minutes_together():
    start = datetime.strptime(START_DATE, "%Y-%m-%d %H:%M")
    return int((datetime.now() - start).total_seconds() // 60)


def days_to_event():
    event = datetime.strptime(DATE_EVENT, "%Y-%m-%d %H:%M")
    delta = event - datetime.now()
    if delta.total_seconds() < 0:
        return "🎉 Уже наступил!"
    return f"{delta.days} дней, {delta.seconds // 3600} часов"


def days_to_bday():
    bday = datetime.strptime(HER_BIRTHDAY, "%Y-%m-%d")
    now = datetime.now()
    next_bday = bday.replace(year=now.year)
    if next_bday < now:
        next_bday = next_bday.replace(year=now.year + 1)
    return (next_bday - now).days


def name_compliment(name):
    letters = {
        "а": "Ангельская", "б": "Бесподобная", "в": "Великолепная",
        "г": "Гениальная", "д": "Добрая", "е": "Единственная",
        "ж": "Желанная", "з": "Заботливая", "и": "Идеальная",
        "к": "Красивая", "л": "Любимая", "м": "Милая",
        "н": "Нежная", "о": "Очаровательная", "п": "Прекрасная",
        "р": "Роскошная", "с": "Солнечная", "т": "Тёплая",
        "у": "Умная", "ф": "Фантастическая", "х": "Хрупкая",
        "ц": "Ценная", "ч": "Чудесная", "ш": "Шикарная",
        "щ": "Щедрая", "э": "Элегантная", "ю": "Юная", "я": "Яркая",
    }
    result = [f"<b>{l.upper()}</b> — {letters[l]}" for l in name.lower().strip() if l in letters]
    if not result:
        return "Ты — самая лучшая 💕"
    return "💐 <b>Твоё имя — это комплимент:</b>\n\n" + "\n".join(result)


# ============================================================
# СОСТОЯНИЯ (FSM)
# ============================================================
class LetterStates(StatesGroup):
    waiting_text = State()
    waiting_date = State()
    waiting_confirm = State()


class SecretStates(StatesGroup):
    waiting_text = State()
    waiting_password = State()
    waiting_open_password = State()


class PastLetterStates(StatesGroup):
    waiting_text = State()
    waiting_trigger = State()


class ThoughtStates(StatesGroup):
    waiting_text = State()


class MomentStates(StatesGroup):
    waiting_text = State()


class ReplyStates(StatesGroup):
    """Для зеркала — ответ ей через бота"""
    waiting_reply = State()


# ============================================================
# МЕНЮ
# ============================================================
def main_menu():
    kb = [
        [KeyboardButton(text="💕 Романтика"),   KeyboardButton(text="🎁 Сюрпризы")],
        [KeyboardButton(text="✨ Особое"),       KeyboardButton(text="🎬 Развлечения")],
        [KeyboardButton(text="📅 Даты"),         KeyboardButton(text="🍽️ Быт")],
        [KeyboardButton(text="📊 Инфо")],
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)


def menu_romance():
    kb = [
        [KeyboardButton(text="💕 Комплимент"),  KeyboardButton(text="🤗 Тёплое")],
        [KeyboardButton(text="💐 По имени"),    KeyboardButton(text="🌸 Стих")],
        [KeyboardButton(text="🌹 Почему люблю"), KeyboardButton(text="💗 Что я люблю")],
        [KeyboardButton(text="💋 Флирт"),        KeyboardButton(text="🌅 Цитата")],
        [KeyboardButton(text="🤗 Забота"),       KeyboardButton(text="💌 Письмо")],
        [KeyboardButton(text="💍 Наше будущее"), KeyboardButton(text="❤️ Люблю тебя")],
        [KeyboardButton(text="💭 Скучаю"),       KeyboardButton(text="⬅️ Назад")],
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)


def menu_surprise():
    kb = [
        [KeyboardButton(text="🎁 Сюрприз"),         KeyboardButton(text="🎲 Рулетка")],
        [KeyboardButton(text="🃏 Карта любви"),     KeyboardButton(text="🎨 Открытка")],
        [KeyboardButton(text="😄 Анекдот"),         KeyboardButton(text="🎁 Подарок")],
        [KeyboardButton(text="🎭 Правда/Действие"), KeyboardButton(text="⬅️ Назад")],
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)


def menu_special():
    kb = [
        [KeyboardButton(text="💌 Мини-письмо"),   KeyboardButton(text="🔐 Секретка")],
        [KeyboardButton(text="🌙 Сон дня"),       KeyboardButton(text="💭 О чём думаю")],
        [KeyboardButton(text="🎯 Любимый момент"), KeyboardButton(text="⬅️ Назад")],
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)


def menu_fun():
    kb = [
        [KeyboardButton(text="🎯 Викторина"),  KeyboardButton(text="🎬 Фильм")],
        [KeyboardButton(text="📺 Сериал"),     KeyboardButton(text="📚 Книга")],
        [KeyboardButton(text="🍽️ Приготовить"), KeyboardButton(text="⬅️ Назад")],
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)


def menu_dates():
    kb = [
        [KeyboardButton(text="📅 Дней вместе"),  KeyboardButton(text="⏰ До вечера")],
        [KeyboardButton(text="🎂 До ДР"),         KeyboardButton(text="💕 Всё время")],
        [KeyboardButton(text="⬅️ Назад")],
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)


def menu_life():
    kb = [
        [KeyboardButton(text="🤗 Обнимашка"),  KeyboardButton(text="😘 Поцелуй")],
        [KeyboardButton(text="📞 Позвони"),     KeyboardButton(text="😴 Поспать")],
        [KeyboardButton(text="💧 Водичка"),     KeyboardButton(text="🍽️ Поела?")],
        [KeyboardButton(text="💪 Мотивашка"),   KeyboardButton(text="⬅️ Назад")],
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)


def menu_info():
    kb = [
        [KeyboardButton(text="📊 Статистика"), KeyboardButton(text="🏆 Достижения")],
        [KeyboardButton(text="📖 О боте"),     KeyboardButton(text="⬅️ Назад")],
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)


def menu_admin():
    """Админ-меню (только для тебя)"""
    kb = [
        [KeyboardButton(text="✍️ Написать письмо"),  KeyboardButton(text="🔐 Создать секретку")],
        [KeyboardButton(text="💭 Добавить мысль"),   KeyboardButton(text="🎯 Добавить момент")],
        [KeyboardButton(text="💌 Письмо из прошлого"), KeyboardButton(text="📋 Мои письма")],
        [KeyboardButton(text="📋 Мои секретки"),     KeyboardButton(text="⬅️ В меню")],
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)


# ============================================================
# БОТ
# ============================================================
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


# ============================================================
# START
# ============================================================
@dp.message(Command("start"))
async def cmd_start(message: Message):
    register_user(message.from_user.id)

    # если ты — показываем админ-меню
    if message.from_user.id == YOUR_ID:
        await message.answer(
            "👑 <b>Привет, хозяин!</b>\n\n"
            "Это твой бот. Выбирай что делать:\n"
            "• ✍️ Написать письмо ей\n"
            "• 🔐 Создать секретку\n"
            "• 💭 Добавить мысль\n"
            "• 🎯 Добавить момент\n"
            "• 💌 Письмо из прошлого\n\n"
            "Или жми <b>⬅️ В меню</b> чтобы увидеть меню как у неё.",
            reply_markup=menu_admin(),
            parse_mode=ParseMode.HTML,
        )
        return

    await message.answer(
        "💕 <b>Привет, любимая!</b>\n\n"
        "Это наш маленький бот-секрет. Здесь я собрал кучу милых вещей только для тебя.\n\n"
        "Выбирай категорию 👇",
        reply_markup=main_menu(),
        parse_mode=ParseMode.HTML,
    )


@dp.message(Command("menu"))
@dp.message(F.text == "⬅️ Назад")
@dp.message(F.text == "⬅️ В меню")
async def cmd_menu(message: Message):
    if message.from_user.id == YOUR_ID:
        await message.answer("👑 Админ-меню:", reply_markup=menu_admin())
    else:
        await message.answer("Главное меню 👇", reply_markup=main_menu())


# ============================================================
# РОМАНТИКА
# ============================================================
@dp.message(F.text == "💕 Романтика")
async def open_romance(message: Message):
    await message.answer("💕 Что хочешь?", reply_markup=menu_romance())


@dp.message(Command("love"))
@dp.message(F.text == "💕 Комплимент")
async def m_compliment(message: Message):
    add_stat(message.from_user.id, "compliment")
    await message.answer(random.choice(msg.COMPLIMENTS))


@dp.message(F.text == "🤗 Тёплое")
async def m_warm(message: Message):
    add_stat(message.from_user.id, "warm")
    await message.answer(get_random_warm())


@dp.message(F.text == "💐 По имени")
async def m_name(message: Message):
    await message.answer("💐 Напиши своё имя — и я скажу, какая ты 💕")


@dp.message(F.text == "🌸 Стих")
async def m_poem(message: Message):
    await message.answer(random.choice(msg.POEMS), parse_mode=ParseMode.HTML)


@dp.message(F.text == "🌹 Почему люблю")
async def m_why(message: Message):
    await message.answer("🌹 " + random.choice(msg.REASONS_LOVE))


@dp.message(F.text == "💗 Что я люблю")
async def m_ilove(message: Message):
    await message.answer(random.choice(msg.ABOUT_YOU))


@dp.message(F.text == "💋 Флирт")
async def m_flirt(message: Message):
    await message.answer(random.choice(msg.FLIRT))


@dp.message(F.text == "🌅 Цитата")
async def m_quote(message: Message):
    await message.answer(random.choice(msg.QUOTES))


@dp.message(F.text == "🤗 Забота")
async def m_care(message: Message):
    await message.answer(random.choice(msg.CARE))


@dp.message(F.text == "💌 Письмо")
async def m_letter(message: Message):
    text = (
        "💌 <b>Письмо для тебя</b>\n\n"
        "<i>Любимая, я хочу сказать тебе кое-что важное.</i>\n\n"
        "<i>Ты — самое дорогое, что у меня есть. Каждый день с тобой — это подарок, "
        "и я не хочу тратить ни минуты на ссоры и обиды.</i>\n\n"
        "<i>Спасибо, что ты рядом. Спасибо за твоё терпение и любовь. "
        "Я обещаю быть лучше для тебя. И для нас.</i>\n\n"
        "<i>Ты — моё всё. Навсегда твой ❤️</i>"
    )
    await message.answer(text, parse_mode=ParseMode.HTML)


@dp.message(F.text == "💍 Наше будущее")
async def m_future(message: Message):
    await message.answer(random.choice(msg.FUTURE))


@dp.message(F.text == "❤️ Люблю тебя")
async def m_love_you(message: Message):
    await message.answer(random.choice(msg.LOVE_YOU))


@dp.message(Command("miss"))
@dp.message(F.text == "💭 Скучаю")
async def m_miss(message: Message):
    add_stat(message.from_user.id, "miss")
    await message.answer(random.choice(msg.MISS_YOU))
    try:
        await bot.send_message(YOUR_ID, "💭 Она СКУЧАЕТ! Напиши ей ❤️")
    except Exception as e:
        print(f"Не удалось уведомить: {e}")


# ============================================================
# СЮРПРИЗЫ
# ============================================================
@dp.message(F.text == "🎁 Сюрпризы")
async def open_surprise(message: Message):
    await message.answer("🎁 Что хочешь?", reply_markup=menu_surprise())


@dp.message(Command("surprise"))
@dp.message(F.text == "🎁 Сюрприз")
async def m_surprise(message: Message):
    await message.answer(random.choice(msg.SURPRISES))


@dp.message(F.text == "🎲 Рулетка")
async def m_roulette(message: Message):
    await message.answer("🎲 Выпало:\n\n" + random.choice(msg.DATES))


@dp.message(F.text == "🃏 Карта любви")
async def m_card(message: Message):
    await message.answer(random.choice(msg.LOVE_CARDS))


@dp.message(F.text == "🎨 Открытка")
async def m_postcard(message: Message):
    await message.answer(random.choice(msg.CARDS), parse_mode=ParseMode.HTML)


@dp.message(F.text == "😄 Анекдот")
async def m_joke(message: Message):
    await message.answer(random.choice(msg.JOKES))


@dp.message(F.text == "🎁 Подарок")
async def m_gift(message: Message):
    await message.answer("🎁 Идея подарка:\n\n" + random.choice(msg.GIFTS))


@dp.message(F.text == "🎭 Правда/Действие")
async def m_truth(message: Message):
    await message.answer(random.choice(msg.TRUTH_OR_DARE), parse_mode=ParseMode.HTML)


# ============================================================
# ✨ ОСОБОЕ (новые фишки)
# ============================================================
@dp.message(F.text == "✨ Особое")
async def open_special(message: Message):
    await message.answer("✨ Что хочешь?", reply_markup=menu_special())


# 💌 Мини-письмо
@dp.message(F.text == "💌 Мини-письмо")
async def m_mini_letter(message: Message):
    await message.answer(random.choice(msg.LETTERS_ASCII))


# 🌙 Сон дня
@dp.message(F.text == "🌙 Сон дня")
async def m_sleep(message: Message):
    await message.answer(random.choice(msg.SLEEPS))


# 💭 О чём думаю
@dp.message(F.text == "💭 О чём думаю")
async def m_thoughts(message: Message):
    db = load_db()
    thoughts = db.get("thoughts", [])
    if not thoughts:
        await message.answer("💭 Пока он ничего не записал... но я уверен — он думает о тебе 💕")
        return
    await message.answer("💭 " + random.choice(thoughts))


# 🎯 Любимый момент
@dp.message(F.text == "🎯 Любимый момент")
async def m_moments(message: Message):
    db = load_db()
    moments = db.get("moments", [])
    if not moments:
        await message.answer("🎯 Пока он не добавил моментов... но я уверен — их много 💕")
        return
    await message.answer("🎯 " + random.choice(moments))


# 🔐 Секретка (для неё)
@dp.message(F.text == "🔐 Секретка")
async def m_secret(message: Message, state: FSMContext):
    if message.from_user.id == YOUR_ID:
        await message.answer("👑 Ты — хозяин. Используй «🔐 Создать секретку» в админ-меню.")
        return

    db = load_db()
    secrets = db.get("secrets", [])
    if not secrets:
        await message.answer("🔐 Пока нет секретов. Но скоро будут 💕")
        return

    await message.answer("🔐 Введи пароль:")
    await state.set_state(SecretStates.waiting_open_password)


@dp.message(SecretStates.waiting_open_password)
async def secret_open_password(message: Message, state: FSMContext):
    password = message.text.strip().lower()
    db = load_db()
    secrets = db.get("secrets", [])

    found = None
    for s in secrets:
        if s.get("password", "").lower() == password:
            found = s
            break

    if found:
        await message.answer(f"🔓 <b>Секрет открыт!</b>\n\n{found['text']}", parse_mode=ParseMode.HTML)
    else:
        await message.answer("❌ Неверный пароль. Попробуй ещё раз или спроси у него 💕")

    await state.clear()


# ============================================================
# ЗЕРКАЛО — она пишет → тебе приходит → ты отвечаешь
# ============================================================
@dp.message(F.text == "✍️ Ответить")
async def m_reply_start(message: Message, state: FSMContext):
    """Только для тебя"""
    if message.from_user.id != YOUR_ID:
        return
    await message.answer("✍️ Напиши текст — я отправлю ей:")
    await state.set_state(ReplyStates.waiting_reply)


@dp.message(ReplyStates.waiting_reply)
async def m_reply_send(message: Message, state: FSMContext):
    if message.from_user.id != YOUR_ID:
        return

    try:
        await bot.send_message(HER_ID, f"💌 {message.text}")
        await message.answer("✅ Отправлено! ❤️", reply_markup=menu_admin())
    except Exception as e:
        await message.answer(f"❌ Не отправилось: {e}")

    await state.clear()


# ============================================================
# АДМИН: НАПИСАТЬ ОТЛОЖЕННОЕ ПИСЬМО
# ============================================================
@dp.message(F.text == "✍️ Написать письмо")
async def admin_letter_start(message: Message, state: FSMContext):
    if message.from_user.id != YOUR_ID:
        return
    await message.answer(
        "✍️ Напиши текст письма.\n\n"
        "Оно будет отправлено ей в назначенный день."
    )
    await state.set_state(LetterStates.waiting_text)


@dp.message(LetterStates.waiting_text)
async def admin_letter_text(message: Message, state: FSMContext):
    if message.from_user.id != YOUR_ID:
        return
    await state.update_data(text=message.text)
    await message.answer(
        "📅 Когда отправить?\n\n"
        "Напиши дату в формате <b>ГГГГ-ММ-ДД ЧЧ:ММ</b>\n"
        "Например: <code>2026-12-31 09:00</code>",
        parse_mode=ParseMode.HTML,
    )
    await state.set_state(LetterStates.waiting_date)


@dp.message(LetterStates.waiting_date)
async def admin_letter_date(message: Message, state: FSMContext):
    if message.from_user.id != YOUR_ID:
        return

    try:
        datetime.strptime(message.text.strip(), "%Y-%m-%d %H:%M")
    except ValueError:
        await message.answer("❌ Неверный формат. Напиши как: <code>2026-12-31 09:00</code>", parse_mode=ParseMode.HTML)
        return

    data = await state.get_data()
    db = load_db()
    db["letters"].append({
        "text": data["text"],
        "send_date": message.text.strip(),
        "sent": False,
    })
    save_db(db)

    await message.answer(
        f"✅ Письмо сохранено!\n\n"
        f"📅 Отправлю: <b>{message.text.strip()}</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=menu_admin(),
    )
    await state.clear()


# 📋 Список писем
@dp.message(F.text == "📋 Мои письма")
async def admin_letters_list(message: Message):
    if message.from_user.id != YOUR_ID:
        return

    db = load_db()
    letters = db.get("letters", [])

    if not letters:
        await message.answer("📋 Писем пока нет.")
        return

    text = "📋 <b>Твои отложенные письма:</b>\n\n"
    for i, l in enumerate(letters, 1):
        status = "✅ отправлено" if l.get("sent") else "⏳ ждёт"
        text += f"{i}. {l['send_date']} — {status}\n"
        text += f"   <i>{l['text'][:50]}...</i>\n\n"

    await message.answer(text, parse_mode=ParseMode.HTML)


# ============================================================
# АДМИН: СОЗДАТЬ СЕКРЕТКУ
# ============================================================
@dp.message(F.text == "🔐 Создать секретку")
async def admin_secret_start(message: Message, state: FSMContext):
    if message.from_user.id != YOUR_ID:
        return
    await message.answer("🔐 Напиши текст секретки:")
    await state.set_state(SecretStates.waiting_text)


@dp.message(SecretStates.waiting_text)
async def admin_secret_text(message: Message, state: FSMContext):
    if message.from_user.id != YOUR_ID:
        return
    await state.update_data(text=message.text)
    await message.answer("🔑 Теперь придумай пароль (слово или фраза):")
    await state.set_state(SecretStates.waiting_password)


@dp.message(SecretStates.waiting_password)
async def admin_secret_password(message: Message, state: FSMContext):
    if message.from_user.id != YOUR_ID:
        return

    password = message.text.strip()
    data = await state.get_data()

    db = load_db()
    db["secrets"].append({
        "text": data["text"],
        "password": password,
    })
    save_db(db)

    await message.answer(
        f"✅ Секретка создана!\n\n"
        f"🔑 Пароль: <code>{password}</code>\n\n"
        f"Она введёт пароль и увидит текст.",
        parse_mode=ParseMode.HTML,
        reply_markup=menu_admin(),
    )
    await state.clear()


# 📋 Список секреток
@dp.message(F.text == "📋 Мои секретки")
async def admin_secrets_list(message: Message):
    if message.from_user.id != YOUR_ID:
        return

    db = load_db()
    secrets = db.get("secrets", [])

    if not secrets:
        await message.answer("📋 Секреток пока нет.")
        return

    text = "📋 <b>Твои секретки:</b>\n\n"
    for i, s in enumerate(secrets, 1):
        text += f"{i}. 🔑 Пароль: <code>{s['password']}</code>\n"
        text += f"   <i>{s['text'][:60]}...</i>\n\n"

    await message.answer(text, parse_mode=ParseMode.HTML)


# ============================================================
# АДМИН: ДОБАВИТЬ МЫСЛЬ
# ============================================================
@dp.message(F.text == "💭 Добавить мысль")
async def admin_thought_start(message: Message, state: FSMContext):
    if message.from_user.id != YOUR_ID:
        return
    await message.answer(
        "💭 Напиши мысль о ней.\n\n"
        "Она сможет спросить «О чём он думает?» и увидеть случайную."
    )
    await state.set_state(ThoughtStates.waiting_text)


@dp.message(ThoughtStates.waiting_text)
async def admin_thought_save(message: Message, state: FSMContext):
    if message.from_user.id != YOUR_ID:
        return

    db = load_db()
    db["thoughts"].append(message.text)
    save_db(db)

    count = len(db["thoughts"])
    await message.answer(
        f"✅ Мысль сохранена! Всего: {count}",
        reply_markup=menu_admin(),
    )
    await state.clear()


# ============================================================
# АДМИН: ДОБАВИТЬ МОМЕНТ
# ============================================================
@dp.message(F.text == "🎯 Добавить момент")
async def admin_moment_start(message: Message, state: FSMContext):
    if message.from_user.id != YOUR_ID:
        return
    await message.answer(
        "🎯 Напиши любимый момент с ней.\n\n"
        "Например: «Как ты засмеялась в машине»"
    )
    await state.set_state(MomentStates.waiting_text)


@dp.message(MomentStates.waiting_text)
async def admin_moment_save(message: Message, state: FSMContext):
    if message.from_user.id != YOUR_ID:
        return

    db = load_db()
    db["moments"].append(message.text)
    save_db(db)

    count = len(db["moments"])
    await message.answer(
        f"✅ Момент сохранён! Всего: {count}",
        reply_markup=menu_admin(),
    )
    await state.clear()


# ============================================================
# АДМИН: ПИСЬМО ИЗ ПРОШЛОГО
# ============================================================
@dp.message(F.text == "💌 Письмо из прошлого")
async def admin_past_letter_start(message: Message, state: FSMContext):
    if message.from_user.id != YOUR_ID:
        return
    await message.answer(
        "💌 Напиши письмо, которое бот отдаст ей в нужный момент.\n\n"
        "Это письмо «от прошлого тебя»."
    )
    await state.set_state(PastLetterStates.waiting_text)


@dp.message(PastLetterStates.waiting_text)
async def admin_past_letter_text(message: Message, state: FSMContext):
    if message.from_user.id != YOUR_ID:
        return
    await state.update_data(text=message.text)
    await message.answer(
        "💌 Когда отдать?\n\n"
        "Напиши дату <b>ГГГГ-ММ-ДД</b> (например <code>2027-01-01</code>)\n"
        "Или напиши <b>по паролю</b> — тогда она сама введёт пароль, чтобы открыть.",
        parse_mode=ParseMode.HTML,
    )
    await state.set_state(PastLetterStates.waiting_trigger)


@dp.message(PastLetterStates.waiting_trigger)
async def admin_past_letter_trigger(message: Message, state: FSMContext):
    if message.from_user.id != YOUR_ID:
        return

    data = await state.get_data()
    trigger = message.text.strip()

    db = load_db()
    db["past_letters"].append({
        "text": data["text"],
        "trigger": trigger,
        "sent": False,
    })
    save_db(db)

    await message.answer(
        f"✅ Письмо из прошлого сохранено!\n\n"
        f"Триггер: <b>{trigger}</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=menu_admin(),
    )
    await state.clear()


# ============================================================
# РАЗВЛЕЧЕНИЯ
# ============================================================
@dp.message(F.text == "🎬 Развлечения")
async def open_fun(message: Message):
    await message.answer("🎬 Что хочешь?", reply_markup=menu_fun())


@dp.message(Command("quiz"))
@dp.message(F.text == "🎯 Викторина")
async def m_quiz(message: Message):
    add_stat(message.from_user.id, "quiz")
    q = random.choice(msg.QUIZ_QUESTIONS)
    text = f"🎯 <b>{q['q']}</b>\n\n"
    for i, a in enumerate(q["a"], 1):
        text += f"{i}. {a}\n"
    text += f"\nПравильный ответ: <b>{q['correct']}</b>"
    await message.answer(text, parse_mode=ParseMode.HTML)


@dp.message(F.text == "🎬 Фильм")
async def m_movie(message: Message):
    await message.answer(random.choice(msg.MOVIES))


@dp.message(F.text == "📺 Сериал")
async def m_series(message: Message):
    await message.answer(random.choice(msg.SERIES))


@dp.message(F.text == "📚 Книга")
async def m_book(message: Message):
    await message.answer(random.choice(msg.BOOKS))


@dp.message(F.text == "🍽️ Приготовить")
async def m_dinner(message: Message):
    await message.answer(random.choice(msg.DINNER_IDEAS))


# ============================================================
# ДАТЫ
# ============================================================
@dp.message(F.text == "📅 Даты")
async def open_dates(message: Message):
    await message.answer("📅 Что хочешь?", reply_markup=menu_dates())


@dp.message(Command("days"))
@dp.message(F.text == "📅 Дней вместе")
async def m_days(message: Message):
    d = days_together()
    await message.answer(
        f"💕 Мы вместе уже <b>{d} дней</b>\n"
        f"Это {d // 30} месяцев и {d % 30} дней\n"
        f"Или {d * 24} часов вместе ❤️",
        parse_mode=ParseMode.HTML,
    )


@dp.message(F.text == "💕 Всё время")
async def m_alltime(message: Message):
    await message.answer(
        f"⏳ <b>Мы вместе:</b>\n\n"
        f"📅 Дней: <b>{days_together()}</b>\n"
        f"⏰ Часов: <b>{hours_together()}</b>\n"
        f"⏱️ Минут: <b>{minutes_together()}</b>\n\n"
        f"И это только начало ♾️",
        parse_mode=ParseMode.HTML,
    )


@dp.message(F.text == "⏰ До вечера")
async def m_countdown(message: Message):
    left = days_to_event()
    await message.answer(
        f"🍷 До нашего романтического вечера осталось:\n\n<b>{left}</b>\n\nГотовься, будет волшебно 💕",
        parse_mode=ParseMode.HTML,
    )


@dp.message(F.text == "🎂 До ДР")
async def m_bday(message: Message):
    left = days_to_bday()
    await message.answer(
        f"🎂 До твоего дня рождения осталось:\n\n<b>{left} дней</b>\n\nГотовься принимать подарки 💕",
        parse_mode=ParseMode.HTML,
    )


# ============================================================
# БЫТ
# ============================================================
@dp.message(F.text == "🍽️ Быт")
async def open_life(message: Message):
    await message.answer("🍽️ Что хочешь?", reply_markup=menu_life())


@dp.message(Command("hug"))
@dp.message(F.text == "🤗 Обнимашка")
async def m_hug(message: Message):
    add_stat(message.from_user.id, "hug")
    await message.answer("🤗 Обнимаю тебя крепко-крепко! Чувствуешь? 💕")
    try:
        await bot.send_message(YOUR_ID, "🤗 Она отправила тебе ОБНИМАШКУ! Обними в ответ ❤️")
    except Exception as e:
        print(f"Не удалось уведомить: {e}")


@dp.message(F.text == "😘 Поцелуй")
async def m_kiss(message: Message):
    await message.answer("😘 Целую тебя в лобик! Самый нежный поцелуй 💕")
    try:
        await bot.send_message(YOUR_ID, "😘 Она послала тебе поцелуй! 💕")
    except Exception as e:
        print(f"Не удалось уведомить: {e}")


@dp.message(F.text == "📞 Позвони")
async def m_call(message: Message):
    await message.answer("📞 Позвони мне, когда сможешь 💕")
    try:
        await bot.send_message(YOUR_ID, "📞 Она просит ПОЗВОНИТЬ! ❤️")
    except Exception as e:
        print(f"Не удалось уведомить: {e}")


@dp.message(F.text == "😴 Поспать")
async def m_sleep_life(message: Message):
    await message.answer("😴 Иди поспи, любимая. Мир подождёт 💕")


@dp.message(F.text == "💧 Водичка")
async def m_water(message: Message):
    await message.answer("💧 Выпей водички, солнышко! Это важно 💕")


@dp.message(F.text == "🍽️ Поела?")
async def m_food(message: Message):
    await message.answer("🍽️ Ты поела? Если нет — иди поешь, я волнуюсь 💕")


@dp.message(F.text == "💪 Мотивашка")
async def m_motivation(message: Message):
    all_moods = msg.MOODS["грустно"] + msg.MOODS["устала"] + msg.MOODS["счастлива"]
    await message.answer(random.choice(all_moods))


# ============================================================
# ИНФО
# ============================================================
@dp.message(F.text == "📊 Инфо")
async def open_info(message: Message):
    await message.answer("📊 Что хочешь?", reply_markup=menu_info())


@dp.message(F.text == "📊 Статистика")
async def m_stats(message: Message):
    db = load_db()
    user_stats = db.get("stats", {}).get(str(message.from_user.id), {})
    if not user_stats:
        await message.answer("📊 Пока пусто! Жми кнопки — я считаю 😊")
        return
    text = "📊 <b>Твоя статистика:</b>\n\n"
    names = {
        "compliment": "💕 Комплименты",
        "hug": "🤗 Обнимашки",
        "miss": "💭 Скучала",
        "quiz": "🎯 Викторина",
        "warm": "🤗 Тёплые",
    }
    total = 0
    for k, v in user_stats.items():
        text += f"{names.get(k, k)}: <b>{v}</b>\n"
        total += v
    text += f"\n💖 Всего: <b>{total}</b> действий"
    await message.answer(text, parse_mode=ParseMode.HTML)


@dp.message(F.text == "🏆 Достижения")
async def m_achieve(message: Message):
    await message.answer(random.choice(msg.ACHIEVEMENTS))


@dp.message(F.text == "📖 О боте")
async def m_about(message: Message):
    await message.answer(
        "📖 <b>О боте</b>\n\n"
        "Этот бот сделан с любовью специально для тебя 💕\n\n"
        "Он умеет очень много:\n"
        "• говорить комплименты\n"
        "• присылать тёплые сообщения\n"
        "• стихи, цитаты, флирт\n"
        "• считать сколько мы вместе\n"
        "• предлагать идеи свиданий\n"
        "• заботиться о тебе\n"
        "• хранить секреты под паролем\n"
        "• присылать сны перед сном\n"
        "• и ещё много всего!\n\n"
        "Исследуй все кнопки 💗",
        parse_mode=ParseMode.HTML,
    )


# ============================================================
# ЗЕРКАЛО — перехват сообщений ей
# ============================================================
@dp.message(F.text)
async def handle_her_messages(message: Message, state: FSMContext):
    """Обрабатывает все сообщения, не попавшие под кнопки"""

    # если это ты — не зеркалим
    if message.from_user.id == YOUR_ID:
        # проверка на имя (комплимент по имени)
        text = message.text.strip()
        if 2 <= len(text) <= 20 and text.replace(" ", "").isalpha():
            await message.answer(name_compliment(text), parse_mode=ParseMode.HTML)
            return
        await message.answer("👑 Жми кнопки админ-меню 👇", reply_markup=menu_admin())
        return

    # это она — зеркало
    add_stat(message.from_user.id, "messages")
    try:
        keyboard = ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="✍️ Ответить")]],
            resize_keyboard=True,
        )
        await bot.send_message(
            YOUR_ID,
            f"💌 <b>Она написала:</b>\n\n{message.text}\n\n"
            f"Жми «✍️ Ответить» чтобы ответить ей от твоего имени.",
            reply_markup=keyboard,
            parse_mode=ParseMode.HTML,
        )
        await message.answer("💭 Я передал ему. Он скоро ответит 💕")
    except Exception as e:
        print(f"Ошибка зеркала: {e}")
        await message.answer("Не понял 🤔 Жми кнопки 👇", reply_markup=main_menu())


# ============================================================
# АВТО-РАССЫЛКА (утро / день / ночь / сон / письма)
# ============================================================
async def send_daily():
    morning_sent = None
    day_sent = None
    night_sent = None
    sleep_sent = None
    today = datetime.now().date()

    while True:
        try:
            now = datetime.now()
            current_date = now.date()

            # сброс в новый день
            if current_date != today:
                morning_sent = day_sent = night_sent = sleep_sent = None
                today = current_date

            hh_mm = now.strftime("%H:%M")

            # утро
            if hh_mm == MORNING_TIME and morning_sent != today:
                try:
                    await bot.send_message(HER_ID, random.choice(msg.GOOD_MORNING))
                    morning_sent = today
                except Exception as e:
                    print(f"Ошибка утра: {e}")

            # комплимент днём
            if hh_mm == DAY_COMPLIMENT_TIME and day_sent != today:
                try:
                    await bot.send_message(HER_ID, random.choice(msg.COMPLIMENTS))
                    day_sent = today
                except Exception as e:
                    print(f"Ошибка дня: {e}")

            # вечер
            if hh_mm == NIGHT_TIME and night_sent != today:
                try:
                    await bot.send_message(HER_ID, random.choice(msg.GOOD_NIGHT))
                    night_sent = today
                except Exception as e:
                    print(f"Ошибка вечера: {e}")

            # сон дня
            if hh_mm == SLEEP_TIME and sleep_sent != today:
                try:
                    await bot.send_message(HER_ID, random.choice(msg.SLEEPS))
                    sleep_sent = today
                except Exception as e:
                    print(f"Ошибка сна: {e}")

            # проверка отложенных писем
            try:
                db = load_db()
                letters = db.get("letters", [])
                changed = False

                for letter in letters:
                    if letter.get("sent"):
                        continue
                    try:
                        send_time = datetime.strptime(letter["send_date"], "%Y-%m-%d %H:%M")
                        if send_time <= now:
                            await bot.send_message(
                                HER_ID,
                                f"💌 <b>Тебе письмо!</b>\n\n{letter['text']}\n\n<i>— Твой ❤️</i>",
                                parse_mode=ParseMode.HTML,
                            )
                            letter["sent"] = True
                            changed = True
                    except Exception as e:
                        print(f"Ошибка письма: {e}")

                # проверка писем из прошлого
                past_letters = db.get("past_letters", [])
                for pl in past_letters:
                    if pl.get("sent"):
                        continue
                    trigger = pl.get("trigger", "")
                    # если это дата
                    try:
                        send_time = datetime.strptime(trigger, "%Y-%m-%d")
                        if send_time.date() <= now.date():
                            await bot.send_message(
                                HER_ID,
                                f"💌 <b>Письмо от прошлого тебя</b>\n\n{pl['text']}\n\n<i>— Он ❤️</i>",
                                parse_mode=ParseMode.HTML,
                            )
                            pl["sent"] = True
                            changed = True
                    except ValueError:
                        # это не дата — значит пароль, пропускаем
                        pass

                if changed:
                    save_db(db)
            except Exception as e:
                print(f"Ошибка проверки писем: {e}")

        except Exception as e:
            print(f"Ошибка в send_daily: {e}")

        await asyncio.sleep(30)


# ============================================================
# ВЕБ-СЕРВЕР (для Render Web Service)
# ============================================================
async def healthcheck(request):
    return web.Response(text="Bot is alive ❤️")


async def start_webserver():
    app = web.Application()
    app.router.add_get("/", healthcheck)
    app.router.add_get("/health", healthcheck)
    port = int(os.environ.get("PORT", 10000))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    print(f"✅ Веб-сервер на порту {port}")


# ============================================================
# MAIN
# ============================================================
async def main():
    asyncio.create_task(start_webserver())
    asyncio.create_task(send_daily())
    print("🚀 Бот запущен!")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())