import asyncio
import logging
import os
from datetime import datetime

from aiogram import Bot, Dispatcher, Router, F
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


def cancel_menu():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="❌ Отмена")]],
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
        f"📊 Бюджет на месяц: {budget.month_key}\n\n"
        f"Доход: {budget.salary:.2f} ₽\n"
        f"Фиксированные траты:\n"
        f"• Аренда: {budget.rent:.2f} ₽\n"
        f"• Коммуналка: {budget.utilities:.2f} ₽\n"
        f"Итого fixed: {budget.fixed_total:.2f} ₽\n\n"
        f"Остаток: {budget.remaining:.2f} ₽\n\n"
        f"Автораспределение:\n"
        f"• Еда: {budget.food:.2f} ₽\n"
        f"• Транспорт: {budget.transport:.2f} ₽\n"
        f"• Накопления: {budget.savings:.2f} ₽\n"
        f"• Развлечения: {budget.entertainment:.2f} ₽\n"
        f"• Здоровье: {budget.health:.2f} ₽\n"
        f"• Прочее: {budget.other:.2f} ₽"
    )


def summarize_operations(operations):
    income = sum(op.amount for op in operations if op.type == "income")
    expense = sum(op.amount for op in operations if op.type == "expense")
    return income, expense, income - expense


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await get_or_create_user(message.from_user.id)
    await state.clear()
    await message.answer(
        "👋 Добро пожаловать в финансового бота.\n"
        "Выберите действие в меню ниже.",
        reply_markup=main_menu(),
    )


@router.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(
        "Доступные разделы:\n\n"
        "💰 Доход — добавить доход\n"
        "💸 Расход — добавить расход\n"
        "📊 Бюджет — рассчитать бюджет месяца\n"
        "💼 Баланс — показать общий баланс\n"
        "📅 Сегодня / 📆 Неделя / 🗓 Месяц — отчеты по периоду\n"
        "📌 Сводка — общая сводка по финансам\n"
        "📜 История — последние операции\n"
        "📂 Бюджет месяца — текущий бюджет\n"
        "📚 Архив бюджетов — прошлые месяцы\n"
        "🎯 Цели — накопительные цели\n"
        "💳 Долги — список долгов\n"
        "🔁 Автоплатежи — регулярные платежи\n"
        "🏦 Фонды — пока MVP-заглушка\n"
        "⚙️ Настройки — пока MVP-заглушка\n\n"
        "Текстовые команды:\n"
        "цель Название 50000\n"
        "долг Название 145000\n"
        "автоплатеж Название 3000",
        reply_markup=main_menu(),
    )


@router.message(F.text == "❌ Отмена")
async def cancel_handler(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("❌ Действие отменено.", reply_markup=main_menu())


@router.message(F.text == "💰 Доход")
async def income_button(message: Message, state: FSMContext):
    await state.set_state(AddIncome.waiting_amount)
    await message.answer("Введите сумму дохода:", reply_markup=cancel_menu())


@router.message(AddIncome.waiting_amount)
async def process_income_amount(message: Message, state: FSMContext):
    try:
        amount = parse_amount(message.text)
        if amount <= 0:
            await message.answer("❌ Сумма должна быть больше 0", reply_markup=cancel_menu())
            return
        await state.update_data(amount=amount)
        await state.set_state(AddIncome.waiting_comment)
        await message.answer("Введите комментарий или '-':", reply_markup=cancel_menu())
    except ValueError:
        await message.answer("❌ Введите сумму числом", reply_markup=cancel_menu())


@router.message(AddIncome.waiting_comment)
async def process_income_comment(message: Message, state: FSMContext):
    data = await state.get_data()
    comment = message.text.strip()
    if comment == "-":
        comment = ""

    await add_operation(message.from_user.id, "income", data["amount"], "Доход", comment)
    balance = await get_balance(message.from_user.id)

    await state.clear()
    await message.answer(
        f"✅ Доход добавлен\n"
        f"Сумма: {data['amount']:.2f} ₽\n"
        f"Баланс: {balance:.2f} ₽",
        reply_markup=main_menu(),
    )


@router.message(F.text == "💸 Расход")
async def expense_button(message: Message, state: FSMContext):
    await state.set_state(AddExpense.waiting_amount)
    await message.answer("Введите сумму расхода:", reply_markup=cancel_menu())


@router.message(AddExpense.waiting_amount)
async def process_expense_amount(message: Message, state: FSMContext):
    try:
        amount = parse_amount(message.text)
        if amount <= 0:
            await message.answer("❌ Сумма должна быть больше 0", reply_markup=cancel_menu())
            return

        await state.update_data(amount=amount)
        await state.set_state(AddExpense.waiting_category)
        await message.answer("Выберите категорию:", reply_markup=expense_categories_menu())
    except ValueError:
        await message.answer("❌ Введите сумму числом", reply_markup=cancel_menu())


@router.message(AddExpense.waiting_category)
async def process_expense_category(message: Message, state: FSMContext):
    category_map = {
        "🍔 Еда": "Еда",
        "🚌 Транспорт": "Транспорт",
        "🎉 Развлечения": "Развлечения",
        "💊 Здоровье": "Здоровье",
        "🧾 Прочее": "Прочее",
    }
    category = category_map.get(message.text.strip(), message.text.strip())
    await state.update_data(category=category)
    await state.set_state(AddExpense.waiting_comment)
    await message.answer("Введите комментарий или '-':", reply_markup=cancel_menu())


@router.message(AddExpense.waiting_comment)
async def process_expense_comment(message: Message, state: FSMContext):
    data = await state.get_data()
    comment = message.text.strip()
    if comment == "-":
        comment = ""

    await add_operation(message.from_user.id, "expense", data["amount"], data["category"], comment)
    balance = await get_balance(message.from_user.id)

    await state.clear()
    await message.answer(
        f"✅ Расход добавлен\n"
        f"Сумма: {data['amount']:.2f} ₽\n"
        f"Категория: {data['category']}\n"
        f"Баланс: {balance:.2f} ₽",
        reply_markup=main_menu(),
    )


@router.message(F.text == "📊 Бюджет")
async def start_budget_flow(message: Message, state: FSMContext):
    month_key = get_current_month_key()
    existing_budget = await get_budget_by_month(message.from_user.id, month_key)

    if existing_budget:
        await message.answer(
            f"На {month_key} бюджет уже есть.\n\n"
            f"{build_budget_text_from_model(existing_budget)}\n\n"
            f"Введите новую зарплату, если хотите пересчитать.",
            reply_markup=cancel_menu(),
        )
    else:
        await message.answer(
            f"Начинаем расчет бюджета на {month_key}.\n"
            f"Введите зарплату за месяц:",
            reply_markup=cancel_menu(),
        )

    await state.set_state(BudgetFlow.waiting_salary)


@router.message(BudgetFlow.waiting_salary)
async def process_budget_salary(message: Message, state: FSMContext):
    try:
        salary = parse_amount(message.text)
        if salary <= 0:
            await message.answer("❌ Зарплата должна быть больше 0", reply_markup=cancel_menu())
            return

        await state.update_data(salary=salary)
        await state.set_state(BudgetFlow.waiting_rent)
        await message.answer("Введите аренду в рублях:", reply_markup=cancel_menu())
    except ValueError:
        await message.answer("❌ Введите сумму числом", reply_markup=cancel_menu())


@router.message(BudgetFlow.waiting_rent)
async def process_budget_rent(message: Message, state: FSMContext):
    try:
        rent = parse_amount(message.text)
        if rent < 0:
            await message.answer("❌ Сумма не может быть отрицательной", reply_markup=cancel_menu())
            return

        await state.update_data(rent=rent)
        await state.set_state(BudgetFlow.waiting_utilities)
        await message.answer("Введите коммуналку в рублях:", reply_markup=cancel_menu())
    except ValueError:
        await message.answer("❌ Введите сумму числом", reply_markup=cancel_menu())


@router.message(BudgetFlow.waiting_utilities)
async def process_budget_utilities(message: Message, state: FSMContext):
    try:
        utilities = parse_amount(message.text)
        if utilities < 0:
            await message.answer("❌ Сумма не может быть отрицательной", reply_markup=cancel_menu())
            return

        data = await state.get_data()
        result = calculate_auto_budget(data["salary"], data["rent"], utilities)

        if result is None:
            await message.answer(
                "❌ Фиксированные расходы превышают доход.",
                reply_markup=cancel_menu(),
            )
            return

        await state.update_data(preview_budget=result)
        await state.set_state(BudgetFlow.preview)

        text = (
            f"📋 Предпросмотр бюджета\n\n"
            f"Доход: {result['salary']:.2f} ₽\n"
            f"Аренда: {result['rent']:.2f} ₽\n"
            f"Коммуналка: {result['utilities']:.2f} ₽\n"
            f"Итого fixed: {result['fixed_total']:.2f} ₽\n"
            f"Остаток: {result['remaining']:.2f} ₽\n\n"
            f"Автораспределение:\n"
            f"• Еда: {result['auto_budget']['Еда']:.2f} ₽\n"
            f"• Транспорт: {result['auto_budget']['Транспорт']:.2f} ₽\n"
            f"• Накопления: {result['auto_budget']['Накопления']:.2f} ₽\n"
            f"• Развлечения: {result['auto_budget']['Развлечения']:.2f} ₽\n"
            f"• Здоровье: {result['auto_budget']['Здоровье']:.2f} ₽\n"
            f"• Прочее: {result['auto_budget']['Прочее']:.2f} ₽"
        )

        await message.answer(text, reply_markup=budget_preview_menu())
    except ValueError:
        await message.answer("❌ Введите сумму числом", reply_markup=cancel_menu())


@router.message(BudgetFlow.preview, F.text == "✅ Сохранить бюджет")
async def save_budget_handler(message: Message, state: FSMContext):
    data = await state.get_data()
    preview_budget = data.get("preview_budget")

    if not preview_budget:
        await message.answer("❌ Нет данных бюджета.", reply_markup=main_menu())
        await state.clear()
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

    await state.clear()
    await message.answer("✅ Бюджет сохранен.", reply_markup=main_menu())


@router.message(BudgetFlow.preview, F.text == "🔁 Пересчитать бюджет")
async def recalc_budget_preview(message: Message, state: FSMContext):
    await state.set_state(BudgetFlow.waiting_salary)
    await message.answer("Введите новую зарплату:", reply_markup=cancel_menu())


@router.message(F.text == "💼 Баланс")
async def balance_button(message: Message):
    balance = await get_balance(message.from_user.id)
    await message.answer(f"💼 Текущий баланс: {balance:.2f} ₽", reply_markup=main_menu())


@router.message(F.text == "📅 Сегодня")
async def today_button(message: Message):
    operations = await get_period_operations(message.from_user.id, 1)

    if not operations:
        await message.answer("За сегодня операций нет.", reply_markup=main_menu())
        return

    today = datetime.now().date()
    operations = [op for op in operations if op.created_at.date() == today]

    if not operations:
        await message.answer("За сегодня операций нет.", reply_markup=main_menu())
        return

    income, expense, total = summarize_operations(operations)

    await message.answer(
        f"📅 Сегодня\n\n"
        f"Доходы: {income:.2f} ₽\n"
        f"Расходы: {expense:.2f} ₽\n"
        f"Итог: {total:.2f} ₽",
        reply_markup=main_menu(),
    )


@router.message(F.text == "📆 Неделя")
async def week_button(message: Message):
    operations = await get_period_operations(message.from_user.id, 7)

    if not operations:
        await message.answer("За неделю операций нет.", reply_markup=main_menu())
        return

    income, expense, total = summarize_operations(operations)

    await message.answer(
        f"📆 Неделя\n\n"
        f"Доходы: {income:.2f} ₽\n"
        f"Расходы: {expense:.2f} ₽\n"
        f"Итог: {total:.2f} ₽",
        reply_markup=main_menu(),
    )


@router.message(F.text == "🗓 Месяц")
async def month_button(message: Message):
    operations = await get_period_operations(message.from_user.id, 30)

    if not operations:
        await message.answer("За месяц операций нет.", reply_markup=main_menu())
        return

    income, expense, total = summarize_operations(operations)

    await message.answer(
        f"🗓 Месяц\n\n"
        f"Доходы: {income:.2f} ₽\n"
        f"Расходы: {expense:.2f} ₽\n"
        f"Итог: {total:.2f} ₽",
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
        f"📌 Общая сводка\n\n"
        f"Баланс: {balance:.2f} ₽\n\n"
        f"За неделю:\n"
        f"• Доходы: {week_income:.2f} ₽\n"
        f"• Расходы: {week_expense:.2f} ₽\n\n"
        f"За месяц:\n"
        f"• Доходы: {month_income:.2f} ₽\n"
        f"• Расходы: {month_expense:.2f} ₽\n"
    )

    if current_budget:
        weekly_safe_limit = current_budget.remaining / 4
        text += (
            f"\nТекущий бюджет:\n"
            f"• Остаток бюджета: {current_budget.remaining:.2f} ₽\n"
            f"• Рекомендуемый недельный лимит: {weekly_safe_limit:.2f} ₽"
        )
    else:
        text += "\nБюджет на текущий месяц пока не создан."

    await message.answer(text, reply_markup=main_menu())


@router.message(F.text == "📜 История")
async def history_button(message: Message):
    operations = await get_recent_operations(message.from_user.id)

    if not operations:
        await message.answer("История операций пуста.", reply_markup=main_menu())
        return

    text = "📜 Последние операции:\n\n"
    for op in operations:
        emoji = "💰" if op.type == "income" else "💸"
        comment = f" ({op.comment})" if op.comment else ""
        text += (
            f"{emoji} {op.amount:.2f} ₽ | {op.category} | "
            f"{op.created_at.strftime('%d.%m %H:%M')}{comment}\n"
        )

    await message.answer(text, reply_markup=main_menu())


@router.message(F.text == "📂 Бюджет месяца")
async def current_budget_button(message: Message):
    budget = await get_budget_by_month(message.from_user.id, get_current_month_key())

    if not budget:
        await message.answer("Бюджет на текущий месяц не найден.", reply_markup=main_menu())
        return

    await message.answer(build_budget_text_from_model(budget), reply_markup=main_menu())


@router.message(F.text == "📚 Архив бюджетов")
async def archive_button(message: Message):
    budgets = await get_budget_archive(message.from_user.id)

    if not budgets:
        await message.answer("Архив бюджетов пуст.", reply_markup=main_menu())
        return

    text = "📚 Архив бюджетов:\n\n"
    for budget in budgets:
        text += (
            f"• {budget.month_key}: доход {budget.salary:.2f} ₽, "
            f"fixed {budget.fixed_total:.2f} ₽, остаток {budget.remaining:.2f} ₽\n"
        )

    await message.answer(text, reply_markup=main_menu())


@router.message(F.text == "🎯 Цели")
async def goals_button(message: Message):
    goals = await get_goals(message.from_user.id)

    if not goals:
        await message.answer(
            "🎯 Целей накопления пока нет.\n\n"
            "Добавление: цель Название 50000",
            reply_markup=main_menu(),
        )
        return

    text = "🎯 Цели накопления:\n\n"
    for goal in goals:
        progress = (goal.current / goal.target * 100) if goal.target else 0
        left = max(goal.target - goal.current, 0)
        text += (
            f"• {goal.name}\n"
            f"  Накоплено: {goal.current:.2f} ₽ / {goal.target:.2f} ₽\n"
            f"  Осталось: {left:.2f} ₽\n"
            f"  Прогресс: {progress:.1f}%\n\n"
        )

    text += "Добавление: цель Название 50000"
    await message.answer(text, reply_markup=main_menu())


@router.message(F.text == "💳 Долги")
async def debts_button(message: Message):
    debts = await get_debts(message.from_user.id)

    if not debts:
        await message.answer(
            "💳 Долгов пока нет.\n\n"
            "Добавление: долг Название 145000",
            reply_markup=main_menu(),
        )
        return

    text = "💳 Долги:\n\n"
    total = 0
    for debt in debts:
        total += debt.amount
        text += f"• {debt.name}: {debt.amount:.2f} ₽\n"

    text += f"\nИтого долгов: {total:.2f} ₽\n\n"
    text += "Добавление: долг Название 145000"

    await message.answer(text, reply_markup=main_menu())


@router.message(F.text == "🔁 Автоплатежи")
async def recurring_button(message: Message):
    recurring = await get_recurring(message.from_user.id)

    if not recurring:
        await message.answer(
            "🔁 Автоплатежей пока нет.\n\n"
            "Добавление: автоплатеж Название 3000",
            reply_markup=main_menu(),
        )
        return

    text = "🔁 Автоплатежи:\n\n"
    total = 0
    for item in recurring:
        total += item.amount
        text += f"• {item.name}: {item.amount:.2f} ₽ / мес\n"

    text += f"\nИтого регулярных платежей: {total:.2f} ₽ / мес\n\n"
    text += "Добавление: автоплатеж Название 3000"

    await message.answer(text, reply_markup=main_menu())


@router.message(F.text == "🏦 Фонды")
async def funds_button(message: Message):
    await message.answer(
        "🏦 Раздел фондов пока не подключен к текущей базе.\n\n"
        "Следующий шаг: добавить в db.py модель Fund и функции get_funds/add_fund.",
        reply_markup=main_menu(),
    )


@router.message(F.text == "⚙️ Настройки")
async def settings_button(message: Message):
    await message.answer(
        "⚙️ Раздел настроек пока в MVP-режиме.\n\n"
        "Следующий шаг: добавить в db.py user settings, время уведомлений и флаги напоминаний.",
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
        f"✅ Цель «{name}» добавлена на {amount:.2f} ₽",
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
        f"✅ Долг «{name}» добавлен: {amount:.2f} ₽",
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
        f"✅ Автоплатеж «{name}» добавлен: {amount:.2f} ₽ / мес",
        reply_markup=main_menu(),
    )


@router.message()
async def fallback_handler(message: Message):
    await message.answer(
        "Не понял сообщение.\n\n"
        "Используйте кнопки меню или команды формата:\n"
        "• цель Подушка 50000\n"
        "• долг Кредит 145000\n"
        "• автоплатеж Интернет 3000",
        reply_markup=main_menu(),
    )


async def main():
    await init_db()
    dp.include_router(router)
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
