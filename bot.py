# -*- coding: utf-8 -*-
"""
Устойчивый бот учёта топлива
"""

import asyncio
import sqlite3
import re
import io
import traceback
from datetime import datetime
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

try:
    import pytesseract
    from PIL import Image, ImageEnhance, ImageOps
    OCR_AVAILABLE = True
except ImportError:
    OCR_AVAILABLE = False
    print("OCR libraries not available")

import os
BOT_TOKEN = os.getenv("BOT_TOKEN") or "8972153975:AAEKilWR2VzrmWTC6j7xxk00ixNuQeD3e2Q"
DEFAULT_CONSUMPTION = 10.0
DEFAULT_TANK = 57.0
PETROL_PRICE = 75.0
GAS_PRICE = 45.0

def main_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="⛽ Заправка")],
            [KeyboardButton(text="📷 Пробег"), KeyboardButton(text="📊 Остаток")],
            [KeyboardButton(text="📈 Статистика"), KeyboardButton(text="⚙️ Расход")]
        ],
        resize_keyboard=True
    )

def yes_no_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да", callback_data="odo_yes"),
         InlineKeyboardButton(text="❌ Нет", callback_data="odo_no")]
    ])

def fuel_type_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⛽ Газ (45 грн)", callback_data="fuel_gas"),
         InlineKeyboardButton(text="🛢 Бензин (75 грн)", callback_data="fuel_petrol")]
    ])

def init_db():
    try:
        conn = sqlite3.connect("fuel.db")
        cur = conn.cursor()
        cur.execute("""CREATE TABLE IF NOT EXISTS fills (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, date TEXT, liters REAL,
            fuel_type TEXT, price_per_liter REAL, odometer INTEGER, cost REAL, km_driven INTEGER)""")
        cur.execute("""CREATE TABLE IF NOT EXISTS settings (
            user_id INTEGER PRIMARY KEY, consumption REAL, tank_volume REAL,
            last_odometer INTEGER, remaining REAL)""")
        conn.commit()
        conn.close()
    except Exception as e:
        print("DB init error:", e)

def get_settings(user_id):
    try:
        conn = sqlite3.connect("fuel.db")
        cur = conn.cursor()
        cur.execute("SELECT consumption, tank_volume, last_odometer, remaining FROM settings WHERE user_id = ?", (user_id,))
        row = cur.fetchone()
        conn.close()
        if row:
            return {"consumption": row[0] or DEFAULT_CONSUMPTION, "tank_volume": row[1] or DEFAULT_TANK,
                    "last_odometer": row[2] or 0, "remaining": row[3] if row[3] is not None else DEFAULT_TANK}
    except:
        pass
    return {"consumption": DEFAULT_CONSUMPTION, "tank_volume": DEFAULT_TANK, "last_odometer": 0, "remaining": DEFAULT_TANK}

def save_settings(user_id, **kwargs):
    try:
        conn = sqlite3.connect("fuel.db")
        cur = conn.cursor()
        cur.execute("SELECT user_id FROM settings WHERE user_id = ?", (user_id,))
        if cur.fetchone():
            for key, value in kwargs.items():
                cur.execute(f"UPDATE settings SET {key} = ? WHERE user_id = ?", (value, user_id))
        else:
            cur.execute("INSERT INTO settings (user_id, consumption, tank_volume, last_odometer, remaining) VALUES (?, ?, ?, ?, ?)",
                        (user_id, kwargs.get("consumption", DEFAULT_CONSUMPTION), kwargs.get("tank_volume", DEFAULT_TANK),
                         kwargs.get("last_odometer", 0), kwargs.get("remaining", DEFAULT_TANK)))
        conn.commit()
        conn.close()
    except Exception as e:
        print("save_settings error:", e)

def add_fill(user_id, liters, fuel_type, price, odometer, km_driven=0):
    try:
        cost = round(liters * price, 2)
        date = datetime.now().strftime("%Y-%m-%d %H:%M")
        conn = sqlite3.connect("fuel.db")
        cur = conn.cursor()
        cur.execute("INSERT INTO fills (user_id, date, liters, fuel_type, price_per_liter, odometer, cost, km_driven) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (user_id, date, liters, fuel_type, price, odometer, cost, km_driven))
        conn.commit()
        conn.close()
        return cost
    except Exception as e:
        print("add_fill error:", e)
        return liters * price

def get_month_stats(user_id):
    try:
        conn = sqlite3.connect("fuel.db")
        cur = conn.cursor()
        month_start = datetime.now().replace(day=1).strftime("%Y-%m-%d")
        cur.execute("SELECT fuel_type, SUM(liters), SUM(cost), COUNT(*), SUM(km_driven) FROM fills WHERE user_id = ? AND date >= ? GROUP BY fuel_type", (user_id, month_start))
        rows = cur.fetchall()
        conn.close()
        return rows
    except:
        return []

def recognize_odometer(image_bytes: bytes) -> list:
    if not OCR_AVAILABLE:
        return []
    candidates = set()
    try:
        img = Image.open(io.BytesIO(image_bytes)).convert("L")
        img = ImageOps.autocontrast(img)
        img = ImageEnhance.Contrast(img).enhance(2.5)
        inv = ImageOps.invert(img)
        for im in [img, inv]:
            w, h = im.size
            big = im.resize((w * 2, h * 2), Image.BILINEAR)
            for psm in ["6", "7"]:
                try:
                    text = pytesseract.image_to_string(big, config=f"--psm {psm} -c tessedit_char_whitelist=0123456789")
                    for n in re.findall(r"\d{5,7}", text):
                        val = int(n)
                        if 10000 < val < 999999:
                            candidates.add(val)
                except:
                    pass
        return sorted(candidates, key=lambda x: (-len(str(x)), -x))[:5]
    except Exception as e:
        print("OCR error:", e)
        return []

class FillStates(StatesGroup):
    waiting_photo = State()
    confirm_odometer = State()
    waiting_odometer_manual = State()
    waiting_liters = State()
    waiting_fuel_type = State()

class OdoStates(StatesGroup):
    waiting_photo = State()
    confirm_odometer = State()
    waiting_odometer_manual = State()

bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

@dp.message(Command("start"))
async def cmd_start(message: Message):
    try:
        user_id = message.from_user.id
        settings = get_settings(user_id)
        save_settings(user_id)
        text = (
            "🚗 <b>Бот учёта топлива</b>\n\n"
            f"Расход: <b>{settings['consumption']} л/100 км</b>\n"
            f"Бак: <b>{settings['tank_volume']} л</b>\n"
            f"Сейчас в баке: <b>{settings['remaining']:.1f} л</b>\n\n"
            "<b>⛽ Заправка</b> — заправка\n"
            "<b>📷 Пробег</b> — обновить одометр"
        )
        await message.answer(text, parse_mode="HTML", reply_markup=main_keyboard())
    except Exception as e:
        print("start error:", e)
        await message.answer("Ошибка. Попробуй ещё раз.")

@dp.message(F.text == "📷 Пробег")
async def cmd_odo_update(message: Message, state: FSMContext):
    await state.set_state(OdoStates.waiting_photo)
    await message.answer("📷 Пришли фото одометра")

@dp.message(OdoStates.waiting_photo, F.photo)
async def odo_process_photo(message: Message, state: FSMContext):
    try:
        await message.answer("🔍 Распознаю...")
        photo = message.photo[-1]
        file = await bot.get_file(photo.file_id)
        image_data = (await bot.download_file(file.file_path)).read()
        candidates = recognize_odometer(image_data)
        if not candidates:
            await state.set_state(OdoStates.waiting_odometer_manual)
            await message.answer("Не распознал. Напиши пробег вручную:")
            return
        best = candidates[0]
        await state.update_data(odometer=best)
        await state.set_state(OdoStates.confirm_odometer)
        text = f"Распознал: <b>{best}</b>\n\n"
        if len(candidates) > 1:
            text += "Другие: " + ", ".join(map(str, candidates[1:4])) + "\n\n"
        text += "Верно?"
        await message.answer(text, parse_mode="HTML", reply_markup=yes_no_keyboard())
    except Exception as e:
        print("odo photo error:", e)
        await state.set_state(OdoStates.waiting_odometer_manual)
        await message.answer("Ошибка распознавания. Напиши пробег вручную:")

@dp.message(OdoStates.waiting_photo)
async def odo_photo_wrong(message: Message):
    await message.answer("Нужно фото.")

@dp.callback_query(F.data == "odo_yes")
async def odo_yes(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    try:
        current = await state.get_state()
        data = await state.get_data()
        odometer = data.get("odometer")
        if not odometer:
            await callback.message.answer("Нет данных. Начни заново.")
            await state.clear()
            return
        if current and "OdoStates" in str(current):
            await process_odometer_update(callback.message, state, callback.from_user.id, odometer)
        else:
            await state.update_data(odometer=odometer)
            await state.set_state(FillStates.waiting_liters)
            await callback.message.edit_reply_markup(reply_markup=None)
            await callback.message.answer(f"✅ Пробег: <b>{odometer}</b>\n\nСколько литров?", parse_mode="HTML")
    except Exception as e:
        print("odo_yes error:", e)
        await callback.message.answer("Ошибка. Напиши /start")

@dp.callback_query(F.data == "odo_no")
async def odo_no(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    try:
        current = await state.get_state()
        await callback.message.edit_reply_markup(reply_markup=None)
        if current and "OdoStates" in str(current):
            await state.set_state(OdoStates.waiting_odometer_manual)
        else:
            await state.set_state(FillStates.waiting_odometer_manual)
        await callback.message.answer("Напиши правильный пробег:")
    except Exception as e:
        print("odo_no error:", e)

@dp.message(OdoStates.confirm_odometer)
@dp.message(FillStates.confirm_odometer)
async def confirm_text(message: Message, state: FSMContext):
    try:
        text = message.text.strip().lower()
        data = await state.get_data()
        current = await state.get_state()
        if text in ("да", "yes", "верно", "ок"):
            odometer = data.get("odometer")
            if current and "OdoStates" in str(current):
                await process_odometer_update(message, state, message.from_user.id, odometer)
            else:
                await state.set_state(FillStates.waiting_liters)
                await message.answer(f"✅ Пробег: <b>{odometer}</b>\n\nСколько литров?", parse_mode="HTML")
        elif text in ("нет", "no"):
            if current and "OdoStates" in str(current):
                await state.set_state(OdoStates.waiting_odometer_manual)
            else:
                await state.set_state(FillStates.waiting_odometer_manual)
            await message.answer("Напиши пробег:")
        else:
            odo = int(re.sub(r'\D', '', text))
            if current and "OdoStates" in str(current):
                await process_odometer_update(message, state, message.from_user.id, odo)
            else:
                await state.update_data(odometer=odo)
                await state.set_state(FillStates.waiting_liters)
                await message.answer(f"✅ Пробег: <b>{odo}</b>\n\nСколько литров?", parse_mode="HTML")
    except Exception as e:
        print("confirm error:", e)
        await message.answer("Напиши число или Да/Нет")

@dp.message(OdoStates.waiting_odometer_manual)
@dp.message(FillStates.waiting_odometer_manual)
async def manual_odo(message: Message, state: FSMContext):
    try:
        odo = int(re.sub(r'\D', '', message.text))
        current = await state.get_state()
        if current and "OdoStates" in str(current):
            await process_odometer_update(message, state, message.from_user.id, odo)
        else:
            await state.update_data(odometer=odo)
            await state.set_state(FillStates.waiting_liters)
            await message.answer(f"✅ Пробег: <b>{odo}</b>\n\nСколько литров?", parse_mode="HTML")
    except:
        await message.answer("Только число.")

async def process_odometer_update(message: Message, state: FSMContext, user_id: int, odometer: int):
    try:
        settings = get_settings(user_id)
        last_odo = settings["last_odometer"]
        consumption = settings["consumption"]
        remaining = settings["remaining"]

        if last_odo == 0:
            save_settings(user_id, last_odometer=odometer)
            await message.answer(f"✅ Пробег сохранён: <b>{odometer} км</b>", parse_mode="HTML", reply_markup=main_keyboard())
            await state.clear()
            return

        if odometer <= last_odo:
            await message.answer(f"Новый пробег ({odometer}) ≤ старому ({last_odo}).")
            await state.clear()
            return

        km_driven = odometer - last_odo
        used = (km_driven / 100) * consumption
        remaining = max(0.0, remaining - used)
        save_settings(user_id, last_odometer=odometer, remaining=remaining)
        km_left = (remaining / consumption) * 100 if consumption > 0 else 0

        text = (
            f"📷 <b>Пробег обновлён</b>\n\n"
            f"Было: {last_odo} → <b>{odometer}</b> км\n"
            f"Проехал: <b>{km_driven} км</b>\n"
            f"Сжёг: <b>{used:.1f} л</b>\n"
            f"⛽ Остаток: <b>{remaining:.1f} л</b> (~{km_left:.0f} км)"
        )
        await message.answer(text, parse_mode="HTML", reply_markup=main_keyboard())
        await state.clear()
    except Exception as e:
        print("process_odometer error:", e)
        await message.answer("Ошибка обновления.")
        await state.clear()

@dp.message(F.text == "⛽ Заправка")
@dp.message(Command("заправка"))
async def cmd_fill_start(message: Message, state: FSMContext):
    await state.set_state(FillStates.waiting_photo)
    await message.answer("📷 Пришли фото одометра")

@dp.message(FillStates.waiting_photo, F.photo)
async def fill_process_photo(message: Message, state: FSMContext):
    try:
        await message.answer("🔍 Распознаю...")
        photo = message.photo[-1]
        file = await bot.get_file(photo.file_id)
        image_data = (await bot.download_file(file.file_path)).read()
        candidates = recognize_odometer(image_data)
        if not candidates:
            await state.set_state(FillStates.waiting_odometer_manual)
            await message.answer("Не распознал. Напиши пробег:")
            return
        best = candidates[0]
        await state.update_data(odometer=best)
        await state.set_state(FillStates.confirm_odometer)
        text = f"Распознал: <b>{best}</b>\n\n"
        if len(candidates) > 1:
            text += "Другие: " + ", ".join(map(str, candidates[1:4])) + "\n\n"
        text += "Верно?"
        await message.answer(text, parse_mode="HTML", reply_markup=yes_no_keyboard())
    except Exception as e:
        print("fill photo error:", e)
        await state.set_state(FillStates.waiting_odometer_manual)
        await message.answer("Ошибка. Напиши пробег вручную:")

@dp.message(FillStates.waiting_photo)
async def fill_photo_wrong(message: Message):
    await message.answer("Нужно фото.")

@dp.message(FillStates.waiting_liters)
async def process_liters(message: Message, state: FSMContext):
    try:
        liters = float(message.text.strip().replace(",", "."))
        await state.update_data(liters=liters)
        await state.set_state(FillStates.waiting_fuel_type)
        await message.answer(f"Заправил: <b>{liters} л</b>\nВыбери тип:", parse_mode="HTML", reply_markup=fuel_type_keyboard())
    except:
        await message.answer("Только число.")

@dp.callback_query(F.data == "fuel_gas")
async def fuel_gas(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    try:
        await state.update_data(fuel_type="gas", fuel_name="Газ", price=GAS_PRICE)
        await callback.message.edit_reply_markup(reply_markup=None)
        await finish_fill(callback.message, state, callback.from_user.id)
    except Exception as e:
        print("fuel_gas error:", e)
        await callback.message.answer("Ошибка. /start")

@dp.callback_query(F.data == "fuel_petrol")
async def fuel_petrol(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    try:
        await state.update_data(fuel_type="petrol", fuel_name="Бензин", price=PETROL_PRICE)
        await callback.message.edit_reply_markup(reply_markup=None)
        await finish_fill(callback.message, state, callback.from_user.id)
    except Exception as e:
        print("fuel_petrol error:", e)
        await callback.message.answer("Ошибка. /start")

async def finish_fill(message: Message, state: FSMContext, user_id: int):
    try:
        data = await state.get_data()
        odometer = data.get("odometer")
        liters = data.get("liters")
        fuel_type = data.get("fuel_type")
        fuel_name = data.get("fuel_name")
        price = data.get("price")
        if None in (odometer, liters, fuel_type, price):
            await message.answer("Не хватает данных. /start")
            await state.clear()
            return
        settings = get_settings(user_id)
        last_odo = settings["last_odometer"]
        consumption = settings["consumption"]
        remaining = settings["remaining"]
        tank = settings["tank_volume"]
        km_driven = 0
        if last_odo > 0 and odometer > last_odo:
            km_driven = odometer - last_odo
            used = (km_driven / 100) * consumption
            remaining = max(0.0, remaining - used)
        remaining = min(tank, remaining + liters)
        cost = add_fill(user_id, liters, fuel_type, price, odometer, km_driven)
        save_settings(user_id, remaining=remaining, last_odometer=odometer)
        economy = liters * (PETROL_PRICE - price) if fuel_type == "gas" else 0
        text = f"✅ <b>Заправка!</b>\n\n{fuel_name}: {liters} л × {price} = <b>{cost:.0f} грн</b>\nПробег: {odometer}\n"
        if km_driven > 0:
            text += f"Проехал: {km_driven} км\n"
        text += f"\n⛽ Остаток: <b>{remaining:.1f} л</b> (~{(remaining/consumption)*100:.0f} км)"
        if economy > 0:
            text += f"\n💰 Экономия: <b>+{economy:.0f} грн</b>"
        await message.answer(text, parse_mode="HTML", reply_markup=main_keyboard())
        await state.clear()
    except Exception as e:
        print("finish_fill error:", e)
        traceback.print_exc()
        await message.answer("Ошибка записи. Попробуй /start")
        await state.clear()

@dp.message(F.text == "📊 Остаток")
async def cmd_remaining(message: Message):
    s = get_settings(message.from_user.id)
    km_left = (s["remaining"] / s["consumption"]) * 100 if s["consumption"] else 0
    await message.answer(f"⛽ <b>{s['remaining']:.1f} л</b>\nХватит на ~{km_left:.0f} км\nПробег: {s['last_odometer']}", parse_mode="HTML")

@dp.message(F.text == "📈 Статистика")
async def cmd_stats(message: Message):
    rows = get_month_stats(message.from_user.id)
    s = get_settings(message.from_user.id)
    if not rows:
        await message.answer("Пока нет заправок.")
        return
    text = "📊 <b>За месяц</b>\n\n"
    total = 0
    eco = 0
    for ft, liters, cost, cnt, km in rows:
        name = "Газ" if ft == "gas" else "Бензин"
        text += f"{name}: {liters:.1f}л | {cost:.0f}грн | {cnt} раз\n"
        total += cost or 0
        if ft == "gas":
            eco += (liters or 0) * (PETROL_PRICE - GAS_PRICE)
    text += f"\nВсего: <b>{total:.0f} грн</b>"
    if eco > 0:
        text += f"\n💰 Экономия: <b>{eco:.0f} грн</b>"
    text += f"\nОстаток: {s['remaining']:.1f} л"
    await message.answer(text, parse_mode="HTML")

@dp.message(F.text == "⚙️ Расход")
async def cmd_cons(message: Message):
    await message.answer("Напиши расход (например 10.5):")

@dp.message(F.text.regexp(r"^\d+[.,]?\d*$"))
async def num_input(message: Message, state: FSMContext):
    if await state.get_state():
        return
    try:
        v = float(message.text.replace(",", "."))
        if 5 <= v <= 25:
            save_settings(message.from_user.id, consumption=v)
            await message.answer(f"✅ Расход: <b>{v}</b> л/100км", parse_mode="HTML")
        elif 30 <= v <= 100:
            save_settings(message.from_user.id, tank_volume=v)
            await message.answer(f"✅ Бак: <b>{v}</b> л", parse_mode="HTML")
    except:
        pass

@dp.message(F.text)
async def fallback(message: Message):
    await message.answer("Используй кнопки 👇", reply_markup=main_keyboard())

async def main():
    init_db()
    print("Бот запущен (устойчивая версия)")
    while True:
        try:
            await dp.start_polling(bot, handle_signals=False)
        except Exception as e:
            print("Polling error:", e)
            traceback.print_exc()
            await asyncio.sleep(5)

if __name__ == "__main__":
    asyncio.run(main())
