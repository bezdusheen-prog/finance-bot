import asyncio
import json
import logging
import os
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.base import BaseStorage, StorageKey
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
)
from dotenv import load_dotenv
from sqlalchemy import BigInteger, Column, DateTime, Integer, String, Text, select

from db import (
    AsyncSessionLocal,
    Base,
    add_debt,
    add_fund,
    add_goal,
    add_operation,
    add_recurring,
    get_balance,
    get_budget_archive,
    get_budget_by_month,
    get_debts,
    get_funds,
    get_goals,
    get_or_create_user,
    get_period_operations,
    get_recent_operations,
    get_recurring,
    get_user_by_telegram_id,
    init_db,
    save_budget,
    update_user_settings,
)

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
logging.getLogger("aiogram.event").setLevel(logging.INFO)

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN is not set")


class FSMStateRecord(Base):
    __tablename__ = "fsm_states"

    id = Column(Integer, primary_key=True)
    bot_id = Column(BigInteger, index=True, nullable=False)
    chat_id = Column(BigInteger, index=True, nullable=False)
    user_id = Column(BigInteger, index=True, nullable=False)
    thread_id = Column(BigInteger, nullable=True)
    business_connection_id = Column(String, nullable=True)
    destiny = Column(String, nullable=False, default="default")
    state = Column(String, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class FSMDataRecord(Base):
    __tablename__ = "fsm_data"

    id = Column(Integer, primary_key=True)
    bot_id = Column(BigInteger, index=True, nullable=False)
    chat_id = Column(BigInteger, index=True, nullable=False)
    user_id = Column(BigInteger, index=True, nullable=False)
    thread_id = Column(BigInteger, nullable=True)
    business_connection_id = Column(String, nullable=True)
    destiny = Column(String, nullable=False, default="default")
    data = Column(Text, nullable=False, default="{}")
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


def _storage_identity(key: StorageKey) -> dict:
    return {
        "bot_id": key.bot_id,
        "chat_id": key.chat_id,
        "user_id": key.user_id,
        "thread_id": key.thread_id,
        "business_connection_id": key.business_connection_id,
        "destiny": key.destiny,
    }


class SQLAlchemyStorage(BaseStorage):
    async def set_state(self, key: StorageKey, state: Optional[str] = None) -> None:
        identity = _storage_identity(key)
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(FSMStateRecord).where(
                    FSMStateRecord.bot_id == identity["bot_id"],
                    FSMStateRecord.chat_id == identity["chat_id"],
                    FSMStateRecord.user_id == identity["user_id"],
                    FSMStateRecord.destiny == identity["destiny"],
                )
            )
            row = result.scalar_one_or_none()
            if row is None:
                row = FSMStateRecord(**identity, state=state)
                session.add(row)
            else:
                row.state = state
            await session.commit()

    async def get_state(self, key: StorageKey) -> Optional[str]:
        identity = _storage_identity(key)
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(FSMStateRecord).where(
                    FSMStateRecord.bot_id == identity["bot_id"],
                    FSMStateRecord.chat_id == identity["chat_id"],
                    FSMStateRecord.user_id == identity["user_id"],
                    FSMStateRecord.destiny == identity["destiny"],
                )
            )
            row = result.scalar_one_or_none()
            return row.state if row else None

    async def set_data(self, key: StorageKey, data: dict[str, Any]) -> None:
        identity = _storage_identity(key)
        payload = json.dumps(data, ensure_ascii=False)
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(FSMDataRecord).where(
                    FSMDataRecord.bot_id == identity["bot_id"],
                    FSMDataRecord.chat_id == identity["chat_id"],
                    FSMDataRecord.user_id == identity["user_id"],
                    FSMDataRecord.destiny == identity["destiny"],
                )
            )
            row = result.scalar_one_or_none()
            if row is None:
                row = FSMDataRecord(**identity, data=payload)
                session.add(row)
            else:
                row.data = payload
            await session.commit()

    async def get_data(self, key: StorageKey) -> dict[str, Any]:
        identity = _storage_identity(key)
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(FSMDataRecord).where(
                    FSMDataRecord.bot_id == identity["bot_id"],
                    FSMDataRecord.chat_id == identity["chat_id"],
                    FSMDataRecord.user_id == identity["user_id"],
                    FSMDataRecord.destiny == identity["destiny"],
                )
            )
            row = result.scalar_one_or_none()
            if not row or not row.data:
                return {}
            return json.loads(row.data)

    async def close(self) -> None:
        return None


bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=SQLAlchemyStorage())
router = Router()

AUTO_DISTRIBUTION = {
    "Еда": 35,
    "Транспорт": 10,
    "Накопления": 25,
    "Развлечения": 10,
    "Здоровье": 10,
    "Прочее": 10,
}

EXPENSE_CATEGORY_MAP = {
    "food": "Еда",
    "transport": "Транспорт",
    "fun": "Развлечения",
    "health": "Здоровье",
    "other": "Прочее",
}

SETTINGS_TIME_OPTIONS = ["08:00", "09:00", "10:00", "20:00"]
SETTINGS_CURRENCY_OPTIONS = ["RUB", "USD", "EUR"]
SETTINGS_LANGUAGE_OPTIONS = ["ru", "en"]


class AddIncomeFlow(StatesGroup):
    waiting_amount = State()
    waiting_comment = State()


class AddExpenseFlow(StatesGroup):
    waiting_amount = State()
    waiting_category = State()
    waiting_comment = State()


class GoalFlow(StatesGroup):
    waiting_name = State()
    waiting_amount = State()


class DebtFlow(StatesGroup):
    waiting_name = State()
    waiting_amount = State()


class RecurringFlow(StatesGroup):
    waiting_name = State()
    waiting_amount = State()


class FundFlow(StatesGroup):
    waiting_name = State()
    waiting_target = State()
    waiting_monthly = State()


class BudgetFlow(StatesGroup):
    waiting_salary = State()
    waiting_rent = State()
    waiting_utilities = State()
    preview_distribution = State()
    editing_distribution = State()
    confirm_distribution = State()


class SettingsFlow(StatesGroup):
    viewing = State()


def root_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🏠 Главная"), KeyboardButton(text="➕ Добавить")],
            [KeyboardButton(text="📊 Бюджет"), KeyboardButton(text="📜 История")],
            [KeyboardButton(text="📌 Сводка"), KeyboardButton(text="⚙️ Еще")],
        ],
        resize_keyboard=True,
    )


def add_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="💰 Доход"), KeyboardButton(text="💸 Расход")],
            [KeyboardButton(text="🎯 Цель"), KeyboardButton(text="💳 Долг")],
            [KeyboardButton(text="🔁 Автоплатеж"), KeyboardButton(text="🏦 Фонд")],
            [KeyboardButton(text="⬅️ Назад")],
        ],
        resize_keyboard=True,
    )


def more_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="💼 Баланс"), KeyboardButton(text="📂 Бюджет месяца")],
            [KeyboardButton(text="📚 Архив бюджетов"), KeyboardButton(text="🎯 Цели")],
            [KeyboardButton(text="💳 Долги"), KeyboardButton(text="🔁 Автоплатежи")],
            [KeyboardButton(text="📅 Сегодня"), KeyboardButton(text="📆 Неделя")],
            [KeyboardButton(text="🗓 Месяц"), KeyboardButton(text="🏦 Фонды")],
            [KeyboardButton(text="⚙️ Настройки"), KeyboardButton(text="⬅️ Назад")],
        ],
        resize_keyboard=True,
    )


def cancel_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="❌ Отмена")]],
        resize_keyboard=True,
    )


def repeat_menu(kind: str) -> ReplyKeyboardMarkup:
    labels = {
        "income": "🔁 Еще доход",
        "expense": "🔁 Еще расход",
        "goal": "🔁 Еще цель",
        "debt": "🔁 Еще долг",
        "recurring": "🔁 Еще автоплатеж",
        "fund": "🔁 Еще фонд",
    }
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=labels[kind]), KeyboardButton(text="➕ Добавить")],
            [KeyboardButton(text="🏠 Главная")],
        ],
        resize_keyboard=True,
    )


def expense_categories_inline() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🍔 Еда", callback_data="cat:food"),
                InlineKeyboardButton(text="🚌 Транспорт", callback_data="cat:transport"),
            ],
            [
                InlineKeyboardButton(text="🎉 Развлечения", callback_data="cat:fun"),
                InlineKeyboardButton(text="💊 Здоровье", callback_data="cat:health"),
            ],
            [InlineKeyboardButton(text="🧾 Прочее", callback_data="cat:other")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="global:cancel")],
        ]
    )


def skip_comment_inline(kind: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Без комментария", callback_data=f"{kind}:skip_comment")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="global:cancel")],
        ]
    )


def budget_preview_inline() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Сохранить", callback_data="budget:save")],
            [InlineKeyboardButton(text="✏️ Изменить", callback_data="budget:edit")],
            [InlineKeyboardButton(text="🔁 Пересчитать", callback_data="budget:recalc")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="global:cancel")],
        ]
    )


def budget_edit_inline() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🍔 Еда", callback_data="budget_edit:Еда"),
                InlineKeyboardButton(text="🚌 Транспорт", callback_data="budget_edit:Транспорт"),
            ],
            [
                InlineKeyboardButton(text="🎉 Развлечения", callback_data="budget_edit:Развлечения"),
                InlineKeyboardButton(text="💊 Здоровье", callback_data="budget_edit:Здоровье"),
            ],
            [
                InlineKeyboardButton(text="💰 Накопления", callback_data="budget_edit:Накопления"),
                InlineKeyboardButton(text="🧾 Прочее", callback_data="budget_edit:Прочее"),
            ],
            [InlineKeyboardButton(text="✅ Готово", callback_data="budget:confirm")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="global:cancel")],
        ]
    )


def budget_confirm_inline() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Подтвердить и сохранить", callback_data="budget:save")],
            [InlineKeyboardButton(text="✏️ Еще править", callback_data="budget:edit")],
            [InlineKeyboardButton(text="🔁 С нуля", callback_data="budget:recalc")],
        ]
    )


def settings_inline(user) -> InlineKeyboardMarkup:
    reminder_label = "🔔 Напоминания: ON" if user and user.reminders_enabled else "🔕 Напоминания: OFF"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=reminder_label, callback_data="settings:toggle_reminders")],
            [
                InlineKeyboardButton(text="💱 Валюта", callback_data="settings:currency"),
                InlineKeyboardButton(text="🌐 Язык", callback_data="settings:language"),
            ],
            [InlineKeyboardButton(text="🕒 Время уведомлений", callback_data="settings:time")],
        ]
    )


def settings_currency_inline() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=code, callback_data=f"settings_currency:{code}") for code in SETTINGS_CURRENCY_OPTIONS]
        ]
    )


def settings_language_inline() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=code.upper(), callback_data=f"settings_language:{code}") for code in SETTINGS_LANGUAGE_OPTIONS]
        ]
    )


def settings_time_inline() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=option, callback_data=f"settings_time:{option}")] for option in SETTINGS_TIME_OPTIONS]
    )


def parse_amount(text: str) -> float:
    cleaned = text.replace(" ", "").replace(",", ".")
    try:
        value = Decimal(cleaned)
    except InvalidOperation as exc:
        raise ValueError("invalid amount") from exc
    return float(value)


async def get_currency_symbol(telegram_id: int) -> str:
    user = await get_user_by_telegram_id(telegram_id)
    if not user:
        return "₽"
    return {"RUB": "₽", "USD": "$", "EUR": "€"}.get(user.default_currency, "₽")


async def money(telegram_id: int, value: float) -> str:
    return f"{value:.2f} {await get_currency_symbol(telegram_id)}"


def get_current_month_key() -> str:
    return datetime.now().strftime("%Y-%m")


def calculate_auto_budget(salary: float, rent: float, utilities: float):
    fixed_total = rent + utilities
    remaining = salary - fixed_total
    if remaining < 0:
        return None
    auto = {category: round(remaining * percent / 100, 2) for category, percent in AUTO_DISTRIBUTION.items()}
    return {
        "salary": salary,
        "rent": rent,
        "utilities": utilities,
        "fixed_total": fixed_total,
        "remaining": remaining,
        "auto_budget": auto,
    }


async def build_budget_preview_text(telegram_id: int, model: dict) -> str:
    auto = model["auto_budget"]
    distributed = round(sum(auto.values()), 2)
    free = round(model["remaining"] - distributed, 2)
    text = (
        "📋 Предпросмотр бюджета\n\n"
        f"Доход: {await money(telegram_id, model['salary'])}\n"
        f"Аренда: {await money(telegram_id, model['rent'])}\n"
        f"Коммуналка: {await money(telegram_id, model['utilities'])}\n"
        f"Fixed: {await money(telegram_id, model['fixed_total'])}\n"
        f"Остаток: {await money(telegram_id, model['remaining'])}\n\n"
        f"🍔 Еда: {await money(telegram_id, auto['Еда'])}\n"
        f"🚌 Транспорт: {await money(telegram_id, auto['Транспорт'])}\n"
        f"💰 Накопления: {await money(telegram_id, auto['Накопления'])}\n"
        f"🎉 Развлечения: {await money(telegram_id, auto['Развлечения'])}\n"
        f"💊 Здоровье: {await money(telegram_id, auto['Здоровье'])}\n"
        f"🧾 Прочее: {await money(telegram_id, auto['Прочее'])}"
    )
    if free != 0:
        text += f"\n\nСвободно не распределено: {await money(telegram_id, free)}"
    return text


async def build_budget_from_db(telegram_id: int, budget) -> str:
    return (
        f"📊 Бюджет: {budget.month_key}\n\n"
        f"Доход: {await money(telegram_id, budget.salary)}\n"
        f"Аренда: {await money(telegram_id, budget.rent)}\n"
        f"Коммуналка: {await money(telegram_id, budget.utilities)}\n"
        f"Fixed: {await money(telegram_id, budget.fixed_total)}\n"
        f"Остаток: {await money(telegram_id, budget.remaining)}\n\n"
        f"🍔 Еда: {await money(telegram_id, budget.food)}\n"
        f"🚌 Транспорт: {await money(telegram_id, budget.transport)}\n"
        f"💰 Накопления: {await money(telegram_id, budget.savings)}\n"
        f"🎉 Развлечения: {await money(telegram_id, budget.entertainment)}\n"
        f"💊 Здоровье: {await money(telegram_id, budget.health)}\n"
        f"🧾 Прочее: {await money(telegram_id, budget.other)}"
    )


async def operation_card(
    telegram_id: int,
    kind: str,
    amount: float,
    category: Optional[str] = None,
    balance: Optional[float] = None,
    name: Optional[str] = None,
) -> str:
    if kind == "income":
        text = f"✅ Доход\n{await money(telegram_id, amount)}"
    elif kind == "expense":
        text = f"✅ Расход\n{await money(telegram_id, amount)}"
        if category:
            text += f" · {category}"
    elif kind == "goal":
        text = f"✅ Цель\n{name} · {await money(telegram_id, amount)}"
    elif kind == "debt":
        text = f"✅ Долг\n{name} · {await money(telegram_id, amount)}"
    elif kind == "recurring":
        text = f"✅ Автоплатеж\n{name} · {await money(telegram_id, amount)}/мес"
    else:
        text = f"✅ Фонд\n{name} · {await money(telegram_id, amount)}"
    if balance is not None:
        text += f"\nБаланс: {await money(telegram_id, balance)}"
    return text


def summarize_operations(operations):
    income = sum(op.amount for op in operations if op.type == "income")
    expense = sum(op.amount for op in operations if op.type == "expense")
    return income, expense, income - expense


async def finalize_flow(message: Message, state: FSMContext, result_text: str, reply_markup):
    await state.clear()
    await message.answer(result_text, reply_markup=reply_markup)


async def show_home(message: Message, text: str = "🏠 Главное меню"):
    await message.answer(text, reply_markup=root_menu())


async def open_budget_entry(message: Message, state: FSMContext):
    await state.clear()
    await state.set_state(BudgetFlow.waiting_salary)
    await message.answer(f"Шаг 1/3 — введите доход за {get_current_month_key()}:", reply_markup=cancel_menu())


async def start_income_flow(message: Message, state: FSMContext):
    await state.clear()
    await state.set_state(AddIncomeFlow.waiting_amount)
    await message.answer("Введите сумму дохода:", reply_markup=cancel_menu())


async def start_expense_flow(message: Message, state: FSMContext):
    await state.clear()
    await state.set_state(AddExpenseFlow.waiting_amount)
    await message.answer("Введите сумму расхода:", reply_markup=cancel_menu())


async def start_goal_flow(message: Message, state: FSMContext):
    await state.clear()
    await state.set_state(GoalFlow.waiting_name)
    await message.answer("Название цели:", reply_markup=cancel_menu())


async def start_debt_flow(message: Message, state: FSMContext):
    await state.clear()
    await state.set_state(DebtFlow.waiting_name)
    await message.answer("Название долга:", reply_markup=cancel_menu())


async def start_recurring_flow(message: Message, state: FSMContext):
    await state.clear()
    await state.set_state(RecurringFlow.waiting_name)
    await message.answer("Название автоплатежа:", reply_markup=cancel_menu())


async def start_fund_flow(message: Message, state: FSMContext):
    await state.clear()
    await state.set_state(FundFlow.waiting_name)
    await message.answer("Название фонда:", reply_markup=cancel_menu())


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await get_or_create_user(message.from_user.id, message.from_user.full_name)
    await state.clear()
    await show_home(message, "👋 Финансовый бот готов")


@router.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(
        "Бот работает через кнопки, а данные хранятся отдельно для каждого пользователя.",
        reply_markup=root_menu(),
    )


@router.callback_query(F.data == "global:cancel")
async def inline_cancel(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await show_home(callback.message, "❌ Действие отменено")
    await callback.answer()


@router.message(F.text == "🏠 Главная")
async def btn_home(message: Message, state: FSMContext):
    await state.clear()
    await show_home(message)


@router.message(F.text == "➕ Добавить")
async def btn_add(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("➕ Что добавить?", reply_markup=add_menu())


@router.message(F.text.in_(["💰 Доход", "🔁 Еще доход", "🔁 Ещё доход"]))
async def btn_income(message: Message, state: FSMContext):
    await start_income_flow(message, state)


@router.message(F.text.in_(["💸 Расход", "🔁 Еще расход", "🔁 Ещё расход"]))
async def btn_expense(message: Message, state: FSMContext):
    await start_expense_flow(message, state)


@router.message(F.text.in_(["🎯 Цель", "🔁 Еще цель", "🔁 Ещё цель"]))
async def btn_goal(message: Message, state: FSMContext):
    await start_goal_flow(message, state)


@router.message(F.text.in_(["💳 Долг", "🔁 Еще долг", "🔁 Ещё долг"]))
async def btn_debt(message: Message, state: FSMContext):
    await start_debt_flow(message, state)


@router.message(F.text.in_(["🔁 Автоплатеж", "🔁 Еще автоплатеж", "🔁 Ещё автоплатеж"]))
async def btn_recurring(message: Message, state: FSMContext):
    await start_recurring_flow(message, state)


@router.message(F.text.in_(["🏦 Фонд", "🔁 Еще фонд", "🔁 Ещё фонд"]))
async def btn_fund(message: Message, state: FSMContext):
    await start_fund_flow(message, state)


@router.message(F.text == "📊 Бюджет")
async def btn_budget(message: Message, state: FSMContext):
    await open_budget_entry(message, state)


@router.message(F.text == "📜 История")
async def btn_history(message: Message, state: FSMContext):
    await state.clear()
    operations = await get_recent_operations(message.from_user.id)
    if not operations:
        await message.answer("📜 История пуста", reply_markup=root_menu())
        return

    text = "📜 Последние операции:\n\n"
    for op in operations[:10]:
        emoji = "💰" if op.type == "income" else "💸"
        text += f"{emoji} {await money(message.from_user.id, op.amount)} · {op.category} · {op.created_at.strftime('%d.%m %H:%M')}\n"
    await message.answer(text, reply_markup=root_menu())


@router.message(F.text == "📌 Сводка")
async def btn_summary(message: Message, state: FSMContext):
    await state.clear()
    balance = await get_balance(message.from_user.id)
    week_ops = await get_period_operations(message.from_user.id, 7)
    month_ops = await get_period_operations(message.from_user.id, 30)
    current_budget = await get_budget_by_month(message.from_user.id, get_current_month_key())
    week_income, week_expense, _ = summarize_operations(week_ops)
    month_income, month_expense, _ = summarize_operations(month_ops)

    text = (
        f"📌 Сводка\n"
        f"Баланс: {await money(message.from_user.id, balance)}\n"
        f"Неделя: +{await money(message.from_user.id, week_income)} / -{await money(message.from_user.id, week_expense)}\n"
        f"Месяц: +{await money(message.from_user.id, month_income)} / -{await money(message.from_user.id, month_expense)}"
    )
    if current_budget:
        text += f"\nЛимит недели: {await money(message.from_user.id, current_budget.remaining / 4)}"

    await message.answer(text, reply_markup=root_menu())


@router.message(F.text.in_(["⚙️ Еще", "⚙ Еще", "⚙️ Ещё", "⚙ Ещё"]))
async def btn_more(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("⚙️ Дополнительно", reply_markup=more_menu())


@router.message(F.text == "💼 Баланс")
async def btn_balance(message: Message, state: FSMContext):
    await state.clear()
    balance = await get_balance(message.from_user.id)
    await message.answer(f"💼 Баланс\n{await money(message.from_user.id, balance)}", reply_markup=more_menu())


@router.message(F.text == "📅 Сегодня")
async def btn_today(message: Message, state: FSMContext):
    await state.clear()
    operations = await get_period_operations(message.from_user.id, 1)
    today = datetime.now().date()
    items = [op for op in operations if op.created_at.date() == today]
    if not items:
        await message.answer("📅 Сегодня пусто", reply_markup=more_menu())
        return

    income, expense, total = summarize_operations(items)
    await message.answer(
        f"📅 Сегодня\nДоходы: {await money(message.from_user.id, income)}\nРасходы: {await money(message.from_user.id, expense)}\nИтог: {await money(message.from_user.id, total)}",
        reply_markup=more_menu(),
    )


@router.message(F.text == "📆 Неделя")
async def btn_week(message: Message, state: FSMContext):
    await state.clear()
    operations = await get_period_operations(message.from_user.id, 7)
    if not operations:
        await message.answer("📆 За неделю пусто", reply_markup=more_menu())
        return

    income, expense, total = summarize_operations(operations)
    await message.answer(
        f"📆 Неделя\nДоходы: {await money(message.from_user.id, income)}\nРасходы: {await money(message.from_user.id, expense)}\nИтог: {await money(message.from_user.id, total)}",
        reply_markup=more_menu(),
    )


@router.message(F.text == "🗓 Месяц")
async def btn_month(message: Message, state: FSMContext):
    await state.clear()
    operations = await get_period_operations(message.from_user.id, 30)
    if not operations:
        await message.answer("🗓 За месяц пусто", reply_markup=more_menu())
        return

    income, expense, total = summarize_operations(operations)
    await message.answer(
        f"🗓 Месяц\nДоходы: {await money(message.from_user.id, income)}\nРасходы: {await money(message.from_user.id, expense)}\nИтог: {await money(message.from_user.id, total)}",
        reply_markup=more_menu(),
    )


@router.message(F.text == "📂 Бюджет месяца")
async def btn_current_budget(message: Message, state: FSMContext):
    await state.clear()
    budget = await get_budget_by_month(message.from_user.id, get_current_month_key())
    if not budget:
        await message.answer("📂 Бюджет не создан\nСоздайте его через «📊 Бюджет»", reply_markup=more_menu())
        return

    await message.answer(await build_budget_from_db(message.from_user.id, budget), reply_markup=more_menu())


@router.message(F.text == "📚 Архив бюджетов")
async def btn_budget_archive(message: Message, state: FSMContext):
    await state.clear()
    budgets = await get_budget_archive(message.from_user.id)
    if not budgets:
        await message.answer("📚 Архив пуст", reply_markup=more_menu())
        return

    text = "📚 Архив бюджетов:\n\n"
    for budget in budgets:
        text += (
            f"{budget.month_key}: {await money(message.from_user.id, budget.salary)} / "
            f"fixed {await money(message.from_user.id, budget.fixed_total)} / "
            f"остаток {await money(message.from_user.id, budget.remaining)}\n"
        )
    await message.answer(text, reply_markup=more_menu())


@router.message(F.text == "🎯 Цели")
async def btn_goals(message: Message, state: FSMContext):
    await state.clear()
    goals = await get_goals(message.from_user.id)
    if not goals:
        await message.answer("🎯 Целей пока нет\nДобавьте первую через «➕ Добавить» → «🎯 Цель»", reply_markup=more_menu())
        return

    text = "🎯 Цели:\n\n"
    for goal in goals:
        progress = (goal.current / goal.target * 100) if goal.target else 0
        text += f"{goal.name}: {await money(message.from_user.id, goal.current)}/{await money(message.from_user.id, goal.target)} ({progress:.1f}%)\n"
    await message.answer(text, reply_markup=more_menu())


@router.message(F.text == "💳 Долги")
async def btn_debts(message: Message, state: FSMContext):
    await state.clear()
    debts = await get_debts(message.from_user.id)
    if not debts:
        await message.answer("💳 Долгов пока нет\nДобавьте первый через «➕ Добавить» → «💳 Долг»", reply_markup=more_menu())
        return

    total = sum(item.amount for item in debts)
    text = "💳 Долги:\n\n"
    for item in debts:
        text += f"{item.name}: {await money(message.from_user.id, item.amount)}\n"
    text += f"\nИтого: {await money(message.from_user.id, total)}"
    await message.answer(text, reply_markup=more_menu())


@router.message(F.text == "🔁 Автоплатежи")
async def btn_recurring_list(message: Message, state: FSMContext):
    await state.clear()
    recurring = await get_recurring(message.from_user.id)
    if not recurring:
        await message.answer("🔁 Автоплатежей нет\nДобавьте первый через «➕ Добавить» → «🔁 Автоплатеж»", reply_markup=more_menu())
        return

    total = sum(item.amount for item in recurring)
    text = "🔁 Автоплатежи:\n\n"
    for item in recurring:
        text += f"{item.name}: {await money(message.from_user.id, item.amount)}/мес\n"
    text += f"\nИтого: {await money(message.from_user.id, total)}/мес"
    await message.answer(text, reply_markup=more_menu())


@router.message(F.text == "🏦 Фонды")
async def btn_funds(message: Message, state: FSMContext):
    await state.clear()
    funds = await get_funds(message.from_user.id)
    if not funds:
        await message.answer("🏦 Фондов пока нет\nДобавьте первый через «➕ Добавить» → «🏦 Фонд»", reply_markup=more_menu())
        return

    text = "🏦 Фонды:\n\n"
    for fund in funds:
        progress = (fund.current_amount / fund.target_amount * 100) if fund.target_amount else 0
        text += f"{fund.name}: {await money(message.from_user.id, fund.current_amount)}/{await money(message.from_user.id, fund.target_amount)} ({progress:.1f}%)\n"
    await message.answer(text, reply_markup=more_menu())


@router.message(F.text == "⚙️ Настройки")
async def btn_settings(message: Message, state: FSMContext):
    await state.set_state(SettingsFlow.viewing)
    user = await get_or_create_user(message.from_user.id)
    text = (
        "⚙️ Настройки\n\n"
        f"Валюта: {user.default_currency}\n"
        f"Язык: {user.language}\n"
        f"Часовой пояс: {user.timezone}\n"
        f"Время уведомлений: {user.notification_time}\n"
        f"Напоминания: {'ON' if user.reminders_enabled else 'OFF'}"
    )
    await message.answer(text, reply_markup=more_menu())
    await message.answer("Изменить параметры:", reply_markup=settings_inline(user))


@router.message(F.text == "⬅️ Назад")
async def btn_back(message: Message, state: FSMContext):
    await state.clear()
    await show_home(message)


@router.message(F.text == "❌ Отмена")
async def btn_cancel(message: Message, state: FSMContext):
    await state.clear()
    await show_home(message, "❌ Действие отменено")


# дальше — твои FSM-хендлеры AddIncomeFlow, AddExpenseFlow, GoalFlow, DebtFlow, RecurringFlow, FundFlow, BudgetFlow
# и настройки — они у тебя уже рабочие, их можно оставить как есть из текущего файла

@router.message()
async def fallback_message(message: Message, state: FSMContext):
    current_state = await state.get_state()
    logger.info("FALLBACK text=%r state=%r user=%s", message.text, current_state, message.from_user.id)
    await message.answer("Используйте кнопки меню.", reply_markup=root_menu())


async def main():
    print("BOT STARTED FROM THIS FILE")
    await init_db()
    dp.include_router(router)
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
