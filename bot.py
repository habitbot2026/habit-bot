import json, os, asyncio
from datetime import date, timedelta
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder

# --- НАСТРОЙКИ ---
BOT_TOKEN = "7277325489:AAFvxDCXSaugUSYQTsuiC41j4zNyynN31dA"
DATA_FILE = "data.json"
RATE = 1                # 1 балл = 1 рубль
BASE_HABIT = 25          # стартовая награда за привычку: 25 ₽
GROWTH = 1.10            # +10% за каждый день серии
POINTS_TASK = 125        # разовая задача = 125 ₽
POINTS_REPEAT = 50       # одно повторение многоразовой = 50 ₽

# --- ЗАГРУЗКА/СОХРАНЕНИЕ ДАННЫХ ---
def load():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {"points": 0.0, "items": [], "history": []}

def save():
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

data = load()
bot = Bot(BOT_TOKEN)
dp = Dispatcher()

# --- МАШИНА СОСТОЯНИЙ (FSM) ---
class Add(StatesGroup):
    type = State()
    text = State()

class Spend(StatesGroup):
    amount = State()
    note = State()

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---
def habit_reward(streak: int) -> float:
    """Баллы за день серии: 25, 27.5, 30.25, ..."""
    return round(BASE_HABIT * GROWTH ** (streak - 1), 1)

def visible(item) -> bool:
    # Многоразовые всегда видны
    if item["type"] == "repeat":
        return True
    # Привычки (daily) видны, если не сделаны сегодня
    if item["type"] == "daily":
        return item.get("last_done") != date.today().isoformat()
    # Разовые видны, пока не сделаны вообще
    return not item.get("done", False)

def add_points(n, note=None):
    data["points"] = round(data["points"] + n, 1)
    data["history"].append({"type": "earn", "amount": n,
                            "date": date.today().isoformat(), "note": note})

def show_points() -> str:
    return f"🏆 {round(data['points'], 1)} баллов (≈{round(data['points'] * RATE, 1)} ₽)"

# --- КЛАВИАТУРЫ И МЕНЮ ---
def main_menu():
    kb = InlineKeyboardBuilder()
    kb.button(text="➕ Добавить", callback_data="add")
    kb.button(text="✅ Сделать/Сделано", callback_data="done")
    kb.button(text="💸 Потратить баллы", callback_data="spend")
    kb.button(text="🏆 Баллы", callback_data="points")
    kb.adjust(1)
    return kb.as_markup()

# --- КОМАНДЫ И ХЕНДЛЕРЫ ---
@dp.message(Command("start"))
async def start(m: Message):
    await m.answer("Привет! " + show_points(), reply_markup=main_menu())

@dp.callback_query(F.data == "add")
async def add_start(c: CallbackQuery, state: FSMContext):
    kb = InlineKeyboardBuilder()
    kb.button(text="📌 Разовая задача", callback_data="type:task")
    kb.button(text="🌅 Привычка (раз в день)", callback_data="type:daily")
    kb.button(text="🔁 Многоразовая", callback_data="type:repeat")
    kb.adjust(1)
    await state.set_state(Add.type)
    await c.message.answer("Какой тип пункта добавить?", reply_markup=kb.as_markup())
    await c.answer()

@dp.callback_query(Add.type, F.data.startswith("type:"))
async def add_type(c: CallbackQuery, state: FSMContext):
    await state.update_data(type=c.data.split(":")[1])
    await state.set_state(Add.text)
    await c.message.answer("Напиши текст пункта одним сообщением:")
    await c.answer()

@dp.message(Add.text)
async def add_text(m: Message, state: FSMContext):
    st = await state.get_data()
    data["items"].append({
        "id": len(data["items"]) + 1,
        "text": m.text,
        "type": st["type"],
        "done": False,
        "last_done": None,
        "streak": 0,
        "count": 0,
        "count_date": None,
    })
    save()
    await state.clear()
    await m.answer("Добавила! ✅", reply_markup=main_menu())

@dp.callback_query(F.data == "done")
async def show_list(c: CallbackQuery):
    active = [it for it in data["items"] if visible(it)]
    if not active:
        await c.message.answer("На сегодня всё чисто 🙂")
        await c.answer()
        return
    kb = InlineKeyboardBuilder()
    for it in active:
        if it["type"] == "repeat":
            label = f"🔁 {it['text']} — выполнено {it['count']} раз"
        elif it["type"] == "daily":
            label = f"🌅 {it['text']} — серия {it['streak']} дн."
        else:
            label = f"📌 {it['text']}"
        kb.button(text=label, callback_data=f"toggle:{it['id']}")
    kb.button(text="⬅️ Меню", callback_data="menu")
    kb.adjust(1)
    await c.message.answer("Нажми на пункт, чтобы отметить:", reply_markup=kb.as_markup())
    await c.answer()

@dp.callback_query(F.data.startswith("toggle:"))
async def toggle(c: CallbackQuery):
    item_id = int(c.data.split(":")[1])
    today = date.today().isoformat()
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    
    for it in data["items"]:
        if it["id"] != item_id:
            continue
        
        if it["type"] == "task" and not it["done"]:
            it["done"] = True
            add_points(POINTS_TASK, f"Разовая задача: {it['text']}")
            msg = f"Готово! +{POINTS_TASK} ₽ 🏆"
            
        elif it["type"] == "daily" and it.get("last_done") != today:
            # Серия продолжается, только если вчера тоже было отмечено
            it["streak"] = it["streak"] + 1 if it.get("last_done") == yesterday else 1
            it["last_done"] = today
            reward = habit_reward(it["streak"])
            add_points(reward, f"Привычка: {it['text']}, день {it['streak']}")
            next_reward = habit_reward(it["streak"] + 1)
            msg = (f"День {it['streak']} серии! +{reward} ₽ 🏆 "
                   f"(завтра будет {next_reward} ₽)")
            
        elif it["type"] == "repeat":
            if it.get("count_date") == today:
                it["count"] += 1
            else:
                it["count"], it["count_date"] = 1, today
            add_points(POINTS_REPEAT, f"Многоразовое: {it['text']}")
            msg = f"Засчитано {it['count']} раз! +{POINTS_REPEAT} ₽ 🏆"
            
        else:
            msg = "Уже отмечено сегодня 🙂"
        break
    
    save()
    await c.message.answer(f"{msg}\nСчётчик: {show_points()}")
    await c.answer()

@dp.callback_query(F.data == "spend")
async def spend_start(c: CallbackQuery, state: FSMContext):
    await state.set_state(Spend.amount)
    await c.message.answer("Сколько баллов списать? Напиши число (можно с копейками, например 27.5):")
    await c.answer()

@dp.message(Spend.amount)
async def spend_amount(m: Message, state: FSMContext):
    try:
        amount = float(m.text.replace(",", "."))
        if amount <= 0:
            await m.answer("Число должно быть больше нуля. Попробуй ещё раз:")
            return
        if amount > data["points"]:
            await m.answer(f"Не хватает! Сейчас у тебя {round(data['points'], 1)} баллов.")
            return
    except ValueError:
        await m.answer("Это не число. Напиши цифрами, сколько списать (допускается точка или запятая):")
        return
    await state.update_data(amount=amount)
    await state.set_state(Spend.note)
    await m.answer("На что потрачено? Напиши заметку (например, «йогурт») или «-», чтобы пропустить:")

@dp.message(Spend.note)
async def spend_note(m: Message, state: FSMContext):
    st = await state.get_data()
    amount = st["amount"]
    note = None if m.text.strip() == "-" else m.text.strip()
    data["points"] = round(data["points"] - amount, 1)
    data["history"].append({"type": "spend", "amount": amount,
                             "date": date.today().isoformat(), "note": note})
    save()
    await state.clear()
    note_txt = f" («{note}»)" if note else ""
    await m.answer(f"✅ Потрачено {amount} баллов{note_txt}. Осталось: {show_points()}.",
                   reply_markup=main_menu())

@dp.callback_query(F.data == "points")
async def points(c: CallbackQuery):
    await c.message.answer(show_points() + " на вкусняшки")
    await c.answer()

@dp.callback_query(F.data == "menu")
async def menu(c: CallbackQuery):
    await c.message.answer("Меню:", reply_markup=main_menu())
    await c.answer()

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
