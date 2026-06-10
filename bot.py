import asyncio
import logging
import os
from datetime import datetime

from aiogram import Bot, Dispatcher, Router, F
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import KeyboardButton, Message, ReplyKeyboardMarkup
from dotenv import load_dotenv

from db import (
    init_db,
    get_or_create_user,
    add_operation,
    get_balance,
    get_recent_operations,
    get_period_operations,
    save_budget,
    get_budget_by_month,
    get_budget_archive,
    add_goal,
    get_goals,
    add_debt,
    get_debts,
    add_recurring,
    get_recurring,
)

load_dotenv()
logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN is not set")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
router = Router()

AUTO_DISTRIBUTION = {
    "Еда": 35,
    "Транспорт": 10,
    "Накопления": 25,
    "Развлечения": 10,
    "Здоровье": 10,
    "Прочее": 10,
}


class AddIncome(StatesGroup):
    waiting_amount = State()
    waiting_comment = State()


class AddExpense(StatesGroup):
    waiting_amount = State()
    waiting_category = State()
    waiting_comment = State()


class BudgetFlow(StatesGroup):
    waiting_salary = State()
    waiting_rent = State()
    waiting_utilities = State()
    preview = State()


def main_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="💰 Доход"), KeyboardButton(text="💸 Расход")],
            [KeyboardButton(text="📊 Бюджет"), KeyboardButton(text="💼 Баланс")],
            [KeyboardButton(text="📅 Сегодня"), KeyboardButton(text="📆 Неделя")],
            [KeyboardButton(text="🗓 Месяц"), KeyboardButton(text="📌 Сводка")],
            [KeyboardButton(text="📜 История"), KeyboardButton(text="📂 Бюджет месяца")],
            [KeyboardButton(text="📚 Архив бюджетов"), KeyboardButton(text="🎯 Цели")],
            [KeyboardButton(text="💳 Долги"), KeyboardButton(text="🔁 Автоплатежи")],
            [KeyboardButton(text="🏦 Фонды"), KeyboardButton(text="⚙️ Настройки")],
        ],
        resize_keyboard=True,
    )


def one_input_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="❌ Отмена")],
        ],
        resize_keyboard=True,
    )


def yes_no_skip_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Без комментария")],
            [KeyboardButton(text="❌ Отмена")],
        ],
        resize_keyboard=True,
    )


def expense_categories_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🍔 Еда"), KeyboardButton(text="🚌 Транспорт")],
            [KeyboardButton(text="🎉 Развлечения"), KeyboardButton(text="💊 Здоровье")],
            [KeyboardButton(text="🧾 Прочее")],
            [KeyboardButton(text="❌ Отмена")],
        ],
        resize_keyboard=True,
    )


def budget_preview_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="✅ Сохранить бюджет")],
            [KeyboardButton(text="🔁 Пересчитать бюджет")],
            [KeyboardButton(text="❌ Отмена")],
        ],
        resize_keyboard=True,
    )


def parse_amount(text: str) -> float:
    return float(text.replace(" ", "").replace(",", "."))


def get_current_month_key():
    return datetime.now().strftime("%Y-%m")


def calculate_auto_budget(salary: float, rent: float, utilities: float):
    fixed_total = rent + utilities
    remaining = salary - fixed_total

    if remaining < 0:
        return None

    auto_budget = {}
    for category, percent in AUTO_DISTRIBUTION.items():
        auto_budget[category] = round(remaining * percent / 100, 2)

    return {
        "salary": salary,
        "rent": rent,
        "utilities": utilities,
        "fixed_total": fixed_total,
        "remaining": remaining,
        "auto_budget": auto_budget,
    }


def build_budget_text_from_model(budget) -> str:
    return (
        f"📊 Бюджет: {budget.month_key}\n\n"
        f"Доход: {budget.salary:.2f} ₽\n"
        f"Аренда: {budget.rent:.2f} ₽\n"
        f"Коммуналка: {budget.utilities:.2f} ₽\n"
        f"Fixed: {budget.fixed_total:.2f} ₽\n"
        f"Остаток: {budget.remaining:.2f} ₽\n\n"
        f"Еда: {budget.food:.2f} ₽\n"
        f"Транспорт: {budget.transport:.2f} ₽\n"
        f"Накопления: {budget.savings:.2f} ₽\n"
        f"Развлечения: {budget.entertainment:.2f} ₽\n"
        f"Здоровье: {budget.health:.2f} ₽\n"
        f"Прочее: {budget.other:.2f} ₽"
    )


def summarize_operations(operations):
    income = sum(op.amount for op in operations if op.type == "income")
    expense = sum(op.amount for op in operations if op.type == "expense")
    return income, expense, income - expense


async def safe_delete_message(chat_id: int, message_id: int | None):
    if not message_id:
        return
    try:
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
    except TelegramBadRequest:
        pass


async def cleanup_messages(chat_id: int, state: FSMContext, current_user_message_id: int | None = None):
    data = await state.get_data()

    bot_prompt_ids = data.get("bot_prompt_ids", [])
    user_message_ids = data.get("user_message_ids", [])

    if current_user_message_id:
        user_message_ids.append(current_user_message_id)

    for mid in bot_prompt_ids:
        await safe_delete_message(chat_id, mid)

    for mid in user_message_ids:
        await safe_delete_message(chat_id, mid)

    await state.update_data(bot_prompt_ids=[], user_message_ids=[])


async def track_prompt(state: FSMContext, sent_message: Message):
    data = await state.get_data()
    ids = data.get("bot_prompt_ids", [])
    ids.append(sent_message.message_id)
    await state.update_data(bot_prompt_ids=ids)


async def track_user_input(state: FSMContext, message: Message):
    data = await state.get_data()
    ids = data.get("user_message_ids", [])
    ids.append(message.message_id)
    await state.update_data(user_message_ids=ids)


async def send_tracked(message: Message, state: FSMContext, text: str, reply_markup=None):
    sent = await message.answer(text, reply_markup=reply_markup)
    await track_prompt(state, sent)
    return sent


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await get_or_create_user(message.from_user.id)
    await state.clear()
    await message.answer(
        "👋 Финансовый бот готов.",
        reply_markup=main_menu(),
    )


@router.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(
        "Все основные действия доступны через кнопки.\n"
        "Вручную обычно нужно вводить только сумму.",
        reply_markup=main_menu(),
    )


@router.message(F.text == "❌ Отмена")
async def cancel_handler(message: Message, state: FSMContext):
    await cleanup_messages(message.chat.id, state, message.message_id)
    await state.clear()
    await message.answer("❌ Отменено", reply_markup=main_menu())


@router.message(F.text == "💰 Доход")
async def income_button(message: Message, state: FSMContext):
    await state.clear()
    await state.set_state(AddIncome.waiting_amount)
    await send_tracked(message, state, "Введите сумму дохода:", reply_markup=one_input_menu())


@router.message(AddIncome.waiting_amount)
async def process_income_amount(message: Message, state: FSMContext):
    await track_user_input(state, message)

    try:
        amount = parse_amount(message.text)
        if amount <= 0:
            await send_tracked(message, state, "❌ Сумма должна быть больше 0", reply_markup=one_input_menu())
            return

        await state.update_data(amount=amount)
        await state.set_state(AddIncome.waiting_comment)
        await send_tracked(
            message,
            state,
            "Комментарий? Если не нужен — нажмите кнопку.",
            reply_markup=yes_no_skip_menu(),
        )
    except ValueError:
        await send_tracked(message, state, "❌ Введите сумму числом", reply_markup=one_input_menu())


@router.message(AddIncome.waiting_comment)
async def process_income_comment(message: Message, state: FSMContext):
    await track_user_input(state, message)

    data = await state.get_data()
    comment = message.text.strip()

    if comment == "Без комментария":
        comment = ""
    elif comment == "-":
        comment = ""

    await add_operation(message.from_user.id, "income", data["amount"], "Доход", comment)
    balance = await get_balance(message.from_user.id)

    await cleanup_messages(message.chat.id, state)
    await state.clear()

    await message.answer(
        f"✅ Доход: {data['amount']:.2f} ₽\nБаланс: {balance:.2f} ₽",
        reply_markup=main_menu(),
    )


@router.message(F.text == "💸 Расход")
async def expense_button(message: Message, state: FSMContext):
    await state.clear()
    await state.set_state(AddExpense.waiting_amount)
    await send_tracked(message, state, "Введите сумму расхода:", reply_markup=one_input_menu())


@router.message(AddExpense.waiting_amount)
async def process_expense_amount(message: Message, state: FSMContext):
    await track_user_input(state, message)

    try:
        amount = parse_amount(message.text)
        if amount <= 0:
            await send_tracked(message, state, "❌ Сумма должна быть больше 0", reply_markup=one_input_menu())
            return

        await state.update_data(amount=amount)
        await state.set_state(AddExpense.waiting_category)
        await send_tracked(message, state, "Выберите категорию:", reply_markup=expense_categories_menu())
    except ValueError:
        await send_tracked(message, state, "❌ Введите сумму числом", reply_markup=one_input_menu())


@router.message(AddExpense.waiting_category)
async def process_expense_category(message: Message, state: FSMContext):
    await track_user_input(state, message)

    category_map = {
        "🍔 Еда": "Еда",
        "🚌 Транспорт": "Транспорт",
        "🎉 Развлечения": "Развлечения",
        "💊 Здоровье": "Здоровье",
        "🧾 Прочее": "Прочее",
    }
    category = category_map.get(message.text.strip())
    if not category:
        await send_tracked(message, state, "❌ Выберите категорию кнопкой", reply_markup=expense_categories_menu())
        return

    await state.update_data(category=category)
    await state.set_state(AddExpense.waiting_comment)
    await send_tracked(
        message,
        state,
        "Комментарий? Если не нужен — нажмите кнопку.",
        reply_markup=yes_no_skip_menu(),
    )


@router.message(AddExpense.waiting_comment)
async def process_expense_comment(message: Message, state: FSMContext):
    await track_user_input(state, message)

    data = await state.get_data()
    comment = message.text.strip()

    if comment == "Без комментария":
        comment = ""
    elif comment == "-":
        comment = ""

    await add_operation(message.from_user.id, "expense", data["amount"], data["category"], comment)
    balance = await get_balance(message.from_user.id)

    await cleanup_messages(message.chat.id, state)
    await state.clear()

    await message.answer(
        f"✅ Расход: {data['amount']:.2f} ₽ · {data['category']}\nБаланс: {balance:.2f} ₽",
        reply_markup=main_menu(),
    )


@router.message(F.text == "📊 Бюджет")
async def start_budget_flow(message: Message, state: FSMContext):
    await state.clear()
    month_key = get_current_month_key()
    existing_budget = await get_budget_by_month(message.from_user.id, month_key)

    await state.set_state(BudgetFlow.waiting_salary)

    if existing_budget:
        await message.answer(
            build_budget_text_from_model(existing_budget),
            reply_markup=main_menu(),
        )
        await send_tracked(message, state, "Введите доход за месяц для пересчета:", reply_markup=one_input_menu())
    else:
        await send_tracked(message, state, f"Введите доход за {month_key}:", reply_markup=one_input_menu())


@router.message(BudgetFlow.waiting_salary)
async def process_budget_salary(message: Message, state: FSMContext):
    await track_user_input(state, message)

    try:
        salary = parse_amount(message.text)
        if salary <= 0:
            await send_tracked(message, state, "❌ Доход должен быть больше 0", reply_markup=one_input_menu())
            return

        await state.update_data(salary=salary)
        await state.set_state(BudgetFlow.waiting_rent)
        await send_tracked(message, state, "Введите аренду:", reply_markup=one_input_menu())
    except ValueError:
        await send_tracked(message, state, "❌ Введите сумму числом", reply_markup=one_input_menu())


@router.message(BudgetFlow.waiting_rent)
async def process_budget_rent(message: Message, state: FSMContext):
    await track_user_input(state, message)

    try:
        rent = parse_amount(message.text)
        if rent < 0:
            await send_tracked(message, state, "❌ Сумма не может быть отрицательной", reply_markup=one_input_menu())
            return

        await state.update_data(rent=rent)
        await state.set_state(BudgetFlow.waiting_utilities)
        await send_tracked(message, state, "Введите коммуналку:", reply_markup=one_input_menu())
    except ValueError:
        await send_tracked(message, state, "❌ Введите сумму числом", reply_markup=one_input_menu())


@router.message(BudgetFlow.waiting_utilities)
async def process_budget_utilities(message: Message, state: FSMContext):
    await track_user_input(state, message)

    try:
        utilities = parse_amount(message.text)
        if utilities < 0:
            await send_tracked(message, state, "❌ Сумма не может быть отрицательной", reply_markup=one_input_menu())
            return

        data = await state.get_data()
        result = calculate_auto_budget(data["salary"], data["rent"], utilities)

        if result is None:
            await send_tracked(message, state, "❌ Fixed-расходы больше дохода", reply_markup=one_input_menu())
            return

        await state.update_data(preview_budget=result)
        await state.set_state(BudgetFlow.preview)

        await cleanup_messages(message.chat.id, state)

        text = (
            f"📋 Предпросмотр\n\n"
            f"Доход: {result['salary']:.2f} ₽\n"
            f"Аренда: {result['rent']:.2f} ₽\n"
            f"Коммуналка: {result['utilities']:.2f} ₽\n"
            f"Fixed: {result['fixed_total']:.2f} ₽\n"
            f"Остаток: {result['remaining']:.2f} ₽\n\n"
            f"Еда: {result['auto_budget']['Еда']:.2f} ₽\n"
            f"Транспорт: {result['auto_budget']['Транспорт']:.2f} ₽\n"
            f"Накопления: {result['auto_budget']['Накопления']:.2f} ₽\n"
            f"Развлечения: {result['auto_budget']['Развлечения']:.2f} ₽\n"
            f"Здоровье: {result['auto_budget']['Здоровье']:.2f} ₽\n"
            f"Прочее: {result['auto_budget']['Прочее']:.2f} ₽"
        )

        preview_msg = await message.answer(text, reply_markup=budget_preview_menu())
        await track_prompt(state, preview_msg)

    except ValueError:
        await send_tracked(message, state, "❌ Введите сумму числом", reply_markup=one_input_menu())


@router.message(BudgetFlow.preview, F.text == "✅ Сохранить бюджет")
async def save_budget_handler(message: Message, state: FSMContext):
    await track_user_input(state, message)

    data = await state.get_data()
    preview_budget = data.get("preview_budget")

    if not preview_budget:
        await cleanup_messages(message.chat.id, state)
        await state.clear()
        await message.answer("❌ Нет данных бюджета", reply_markup=main_menu())
        return

    await save_budget(
        telegram_id=message.from_user.id,
        month_key=get_current_month_key(),
        salary=preview_budget["salary"],
        rent=preview_budget["rent"],
        utilities=preview_budget["utilities"],
        fixed_total=preview_budget["fixed_total"],
        remaining=preview_budget["remaining"],
        auto_budget=preview_budget["auto_budget"],
    )

    await cleanup_messages(message.chat.id, state)
    await state.clear()

    await message.answer("✅ Бюджет сохранен", reply_markup=main_menu())


@router.message(BudgetFlow.preview, F.text == "🔁 Пересчитать бюджет")
async def recalc_budget_preview(message: Message, state: FSMContext):
    await track_user_input(state, message)
    await cleanup_messages(message.chat.id, state)
    await state.set_state(BudgetFlow.waiting_salary)
    await send_tracked(message, state, "Введите новый доход:", reply_markup=one_input_menu())


@router.message(F.text == "💼 Баланс")
async def balance_button(message: Message):
    balance = await get_balance(message.from_user.id)
    await message.answer(f"💼 Баланс: {balance:.2f} ₽", reply_markup=main_menu())


@router.message(F.text == "📅 Сегодня")
async def today_button(message: Message):
    operations = await get_period_operations(message.from_user.id, 1)

    if not operations:
        await message.answer("📅 Сегодня пусто", reply_markup=main_menu())
        return

    today = datetime.now().date()
    operations = [op for op in operations if op.created_at.date() == today]

    if not operations:
        await message.answer("📅 Сегодня пусто", reply_markup=main_menu())
        return

    income, expense, total = summarize_operations(operations)

    await message.answer(
        f"📅 Сегодня\nДоходы: {income:.2f} ₽\nРасходы: {expense:.2f} ₽\nИтог: {total:.2f} ₽",
        reply_markup=main_menu(),
    )


@router.message(F.text == "📆 Неделя")
async def week_button(message: Message):
    operations = await get_period_operations(message.from_user.id, 7)

    if not operations:
        await message.answer("📆 За неделю пусто", reply_markup=main_menu())
        return

    income, expense, total = summarize_operations(operations)

    await message.answer(
        f"📆 Неделя\nДоходы: {income:.2f} ₽\nРасходы: {expense:.2f} ₽\nИтог: {total:.2f} ₽",
        reply_markup=main_menu(),
    )


@router.message(F.text == "🗓 Месяц")
async def month_button(message: Message):
    operations = await get_period_operations(message.from_user.id, 30)

    if not operations:
        await message.answer("🗓 За месяц пусто", reply_markup=main_menu())
        return

    income, expense, total = summarize_operations(operations)

    await message.answer(
        f"🗓 Месяц\nДоходы: {income:.2f} ₽\nРасходы: {expense:.2f} ₽\nИтог: {total:.2f} ₽",
        reply_markup=main_menu(),
    )


@router.message(F.text == "📌 Сводка")
async def summary_button(message: Message):
    balance = await get_balance(message.from_user.id)
    week_ops = await get_period_operations(message.from_user.id, 7)
    month_ops = await get_period_operations(message.from_user.id, 30)
    current_budget = await get_budget_by_month(message.from_user.id, get_current_month_key())

    week_income, week_expense, _ = summarize_operations(week_ops)
    month_income, month_expense, _ = summarize_operations(month_ops)

    text = (
        f"📌 Сводка\n"
        f"Баланс: {balance:.2f} ₽\n"
        f"Неделя: +{week_income:.2f} / -{week_expense:.2f} ₽\n"
        f"Месяц: +{month_income:.2f} / -{month_expense:.2f} ₽"
    )

    if current_budget:
        weekly_safe_limit = current_budget.remaining / 4
        text += f"\nЛимит недели: {weekly_safe_limit:.2f} ₽"

    await message.answer(text, reply_markup=main_menu())


@router.message(F.text == "📜 История")
async def history_button(message: Message):
    operations = await get_recent_operations(message.from_user.id)

    if not operations:
        await message.answer("📜 История пуста", reply_markup=main_menu())
        return

    text = "📜 Последние операции:\n\n"
    for op in operations:
        emoji = "💰" if op.type == "income" else "💸"
        text += f"{emoji} {op.amount:.2f} ₽ · {op.category} · {op.created_at.strftime('%d.%m %H:%M')}\n"

    await message.answer(text, reply_markup=main_menu())


@router.message(F.text == "📂 Бюджет месяца")
async def current_budget_button(message: Message):
    budget = await get_budget_by_month(message.from_user.id, get_current_month_key())

    if not budget:
        await message.answer("📂 Бюджет не создан", reply_markup=main_menu())
        return

    await message.answer(build_budget_text_from_model(budget), reply_markup=main_menu())


@router.message(F.text == "📚 Архив бюджетов")
async def archive_button(message: Message):
    budgets = await get_budget_archive(message.from_user.id)

    if not budgets:
        await message.answer("📚 Архив пуст", reply_markup=main_menu())
        return

    text = "📚 Архив:\n\n"
    for budget in budgets:
        text += (
            f"{budget.month_key}: "
            f"{budget.salary:.2f} ₽ / fixed {budget.fixed_total:.2f} ₽ / остаток {budget.remaining:.2f} ₽\n"
        )

    await message.answer(text, reply_markup=main_menu())


@router.message(F.text == "🎯 Цели")
async def goals_button(message: Message):
    goals = await get_goals(message.from_user.id)

    if not goals:
        await message.answer(
            "🎯 Целей пока нет\nФормат: цель Название 50000",
            reply_markup=main_menu(),
        )
        return

    text = "🎯 Цели:\n\n"
    for goal in goals:
        progress = (goal.current / goal.target * 100) if goal.target else 0
        text += f"{goal.name}: {goal.current:.2f}/{goal.target:.2f} ₽ ({progress:.1f}%)\n"

    await message.answer(text, reply_markup=main_menu())


@router.message(F.text == "💳 Долги")
async def debts_button(message: Message):
    debts = await get_debts(message.from_user.id)

    if not debts:
        await message.answer(
            "💳 Долгов пока нет\nФормат: долг Название 145000",
            reply_markup=main_menu(),
        )
        return

    total = sum(debt.amount for debt in debts)
    text = "💳 Долги:\n\n"
    for debt in debts:
        text += f"{debt.name}: {debt.amount:.2f} ₽\n"
    text += f"\nИтого: {total:.2f} ₽"

    await message.answer(text, reply_markup=main_menu())


@router.message(F.text == "🔁 Автоплатежи")
async def recurring_button(message: Message):
    recurring = await get_recurring(message.from_user.id)

    if not recurring:
        await message.answer(
            "🔁 Автоплатежей нет\nФормат: автоплатеж Название 3000",
            reply_markup=main_menu(),
        )
        return

    total = sum(item.amount for item in recurring)
    text = "🔁 Автоплатежи:\n\n"
    for item in recurring:
        text += f"{item.name}: {item.amount:.2f} ₽/мес\n"
    text += f"\nИтого: {total:.2f} ₽/мес"

    await message.answer(text, reply_markup=main_menu())


@router.message(F.text == "🏦 Фонды")
async def funds_button(message: Message):
    await message.answer(
        "🏦 Фонды пока не подключены",
        reply_markup=main_menu(),
    )


@router.message(F.text == "⚙️ Настройки")
async def settings_button(message: Message):
    await message.answer(
        "⚙️ Настройки пока в MVP",
        reply_markup=main_menu(),
    )


@router.message(F.text.regexp(r"^цель\s+.+\s+\d+[.,]?\d*$"))
async def add_goal_handler(message: Message):
    match = message.text.strip().rsplit(" ", 1)
    left, amount_str = match
    name = left.replace("цель", "", 1).strip()
    amount = parse_amount(amount_str)

    await add_goal(message.from_user.id, name, amount)
    await message.answer(
        f"✅ Цель: {name} · {amount:.2f} ₽",
        reply_markup=main_menu(),
    )


@router.message(F.text.regexp(r"^долг\s+.+\s+\d+[.,]?\d*$"))
async def add_debt_handler(message: Message):
    match = message.text.strip().rsplit(" ", 1)
    left, amount_str = match
    name = left.replace("долг", "", 1).strip()
    amount = parse_amount(amount_str)

    await add_debt(message.from_user.id, name, amount)
    await message.answer(
        f"✅ Долг: {name} · {amount:.2f} ₽",
        reply_markup=main_menu(),
    )


@router.message(F.text.regexp(r"^автоплатеж\s+.+\s+\d+[.,]?\d*$"))
async def add_recurring_handler(message: Message):
    match = message.text.strip().rsplit(" ", 1)
    left, amount_str = match
    name = left.replace("автоплатеж", "", 1).strip()
    amount = parse_amount(amount_str)

    await add_recurring(message.from_user.id, name, amount)
    await message.answer(
        f"✅ Автоплатеж: {name} · {amount:.2f} ₽/мес",
        reply_markup=main_menu(),
    )


@router.message()
async def fallback_handler(message: Message):
    await message.answer(
        "Используйте кнопки меню.\n"
        "Текстом сейчас: цель / долг / автоплатеж.",
        reply_markup=main_menu(),
    )


async def main():
    await init_db()
    dp.include_router(router)
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
