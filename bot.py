import asyncio
import json
import logging
import os
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from aiogram import Bot, Dispatcher, F, Router
from aiogram.exceptions import TelegramBadRequest
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


def home_inline() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="💰 Доход", callback_data="home:income"),
                InlineKeyboardButton(text="💸 Расход", callback_data="home:expense"),
            ],
            [
                InlineKeyboardButton(text="📊 Бюджет", callback_data="home:budget"),
                InlineKeyboardButton(text="📜 История", callback_data="home:history"),
            ],
            [
                InlineKeyboardButton(text="💼 Баланс", callback_data="home:balance"),
                InlineKeyboardButton(text="📌 Сводка", callback_data="home:summary"),
            ],
        ]
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


def quick_after_action_inline(kind: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔁 Повторить", callback_data=f"again:{kind}")],
            [
                InlineKeyboardButton(text="🏠 Меню", callback_data="home:menu"),
                InlineKeyboardButton(text="➕ Добавить", callback_data="home:add"),
            ],
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
            [InlineKeyboardButton(text="🏠 Меню", callback_data="home:menu")],
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


async def safe_delete_message(chat_id: int, message_id: Optional[int]):
    if not message_id:
        return
    try:
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
    except TelegramBadRequest:
        pass


async def remember_prompt(state: FSMContext, message_id: int):
    data = await state.get_data()
    ids = data.get("bot_prompt_ids", [])
    ids.append(message_id)
    await state.update_data(bot_prompt_ids=ids)


async def remember_user_message(state: FSMContext, message_id: int):
    data = await state.get_data()
    ids = data.get("user_message_ids", [])
    ids.append(message_id)
    await state.update_data(user_message_ids=ids)


async def cleanup_flow_messages(chat_id: int, state: FSMContext, current_message_id: Optional[int] = None):
    data = await state.get_data()
    for mid in data.get("bot_prompt_ids", []):
        await safe_delete_message(chat_id, mid)
    for mid in data.get("user_message_ids", []):
        await safe_delete_message(chat_id, mid)
    if current_message_id:
        await safe_delete_message(chat_id, current_message_id)
    await state.update_data(bot_prompt_ids=[], user_message_ids=[])


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
    return (
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


async def send_tracked(message: Message, state: FSMContext, text: str, reply_markup=None):
    sent = await message.answer(text, reply_markup=reply_markup)
    await remember_prompt(state, sent.message_id)
    return sent


async def show_home(message: Message, text: str = "🏠 Главное меню"):
    await message.answer(text, reply_markup=root_menu())
    await message.answer("Быстрые действия:", reply_markup=home_inline())


async def start_income_flow(message: Message, state: FSMContext):
    await state.clear()
    await state.set_state(AddIncomeFlow.waiting_amount)
    await send_tracked(message, state, "Введите сумму дохода:", reply_markup=cancel_menu())


async def start_expense_flow(message: Message, state: FSMContext):
    await state.clear()
    await state.set_state(AddExpenseFlow.waiting_amount)
    await send_tracked(message, state, "Введите сумму расхода:", reply_markup=cancel_menu())


async def start_goal_flow(message: Message, state: FSMContext):
    await state.clear()
    await state.set_state(GoalFlow.waiting_name)
    await send_tracked(message, state, "Название цели:", reply_markup=cancel_menu())


async def start_debt_flow(message: Message, state: FSMContext):
    await state.clear()
    await state.set_state(DebtFlow.waiting_name)
    await send_tracked(message, state, "Название долга:", reply_markup=cancel_menu())


async def start_recurring_flow(message: Message, state: FSMContext):
    await state.clear()
    await state.set_state(RecurringFlow.waiting_name)
    await send_tracked(message, state, "Название автоплатежа:", reply_markup=cancel_menu())


async def start_fund_flow(message: Message, state: FSMContext):
    await state.clear()
    await state.set_state(FundFlow.waiting_name)
    await send_tracked(message, state, "Название фонда:", reply_markup=cancel_menu())


async def start_budget_flow(message: Message, state: FSMContext):
    await state.clear()
    month_key = get_current_month_key()
    existing = await get_budget_by_month(message.from_user.id, month_key)
    if existing:
        await message.answer(await build_budget_from_db(message.from_user.id, existing), reply_markup=root_menu())
    await state.set_state(BudgetFlow.waiting_salary)
    await send_tracked(message, state, f"Шаг 1/3 — введите доход за {month_key}:", reply_markup=cancel_menu())


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


@router.message(F.text == "🏠 Главная")
async def home_button(message: Message, state: FSMContext):
    await state.clear()
    await show_home(message)


@router.message(F.text == "➕ Добавить")
async def add_button(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("➕ Что добавить?", reply_markup=add_menu())


@router.message(F.text == "⚙️ Еще")
async def more_button(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("⚙️ Дополнительно", reply_markup=more_menu())


@router.message(F.text == "⬅️ Назад")
async def back_button(message: Message, state: FSMContext):
    await state.clear()
    await show_home(message)


@router.message(F.text == "❌ Отмена")
async def cancel_button(message: Message, state: FSMContext):
    await cleanup_flow_messages(message.chat.id, state, message.message_id)
    await state.clear()
    await show_home(message, "❌ Действие отменено")


@router.callback_query(F.data == "global:cancel")
async def inline_cancel(callback: CallbackQuery, state: FSMContext):
    await cleanup_flow_messages(callback.message.chat.id, state)
    await state.clear()
    await show_home(callback.message, "❌ Действие отменено")
    await callback.answer()


@router.callback_query(F.data == "home:menu")
async def inline_home_menu(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await show_home(callback.message)
    await callback.answer()


@router.callback_query(F.data == "home:add")
async def inline_home_add(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.answer("➕ Что добавить?", reply_markup=add_menu())
    await callback.answer()


@router.callback_query(F.data == "home:income")
async def inline_income(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await start_income_flow(callback.message, state)


@router.callback_query(F.data == "home:expense")
async def inline_expense(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await start_expense_flow(callback.message, state)


@router.callback_query(F.data == "home:budget")
async def inline_budget(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await start_budget_flow(callback.message, state)


@router.callback_query(F.data == "home:history")
async def inline_history(callback: CallbackQuery):
    operations = await get_recent_operations(callback.from_user.id)
    if not operations:
        await callback.message.answer("📜 История пуста", reply_markup=root_menu())
    else:
        text = "📜 Последние операции:\n\n"
        for op in operations[:10]:
            emoji = "💰" if op.type == "income" else "💸"
            text += f"{emoji} {await money(callback.from_user.id, op.amount)} · {op.category} · {op.created_at.strftime('%d.%m %H:%M')}\n"
        await callback.message.answer(text, reply_markup=root_menu())
    await callback.answer()


@router.callback_query(F.data == "home:balance")
async def inline_balance(callback: CallbackQuery):
    balance = await get_balance(callback.from_user.id)
    await callback.message.answer(
        f"💼 Баланс\n{await money(callback.from_user.id, balance)}",
        reply_markup=root_menu(),
    )
    await callback.answer()


@router.callback_query(F.data == "home:summary")
async def inline_summary(callback: CallbackQuery):
    balance = await get_balance(callback.from_user.id)
    week_ops = await get_period_operations(callback.from_user.id, 7)
    month_ops = await get_period_operations(callback.from_user.id, 30)
    current_budget = await get_budget_by_month(callback.from_user.id, get_current_month_key())
    week_income, week_expense, _ = summarize_operations(week_ops)
    month_income, month_expense, _ = summarize_operations(month_ops)

    text = (
        f"📌 Сводка\n"
        f"Баланс: {await money(callback.from_user.id, balance)}\n"
        f"Неделя: +{await money(callback.from_user.id, week_income)} / -{await money(callback.from_user.id, week_expense)}\n"
        f"Месяц: +{await money(callback.from_user.id, month_income)} / -{await money(callback.from_user.id, month_expense)}"
    )
    if current_budget:
        text += f"\nЛимит недели: {await money(callback.from_user.id, current_budget.remaining / 4)}"

    await callback.message.answer(text, reply_markup=root_menu())
    await callback.answer()


@router.callback_query(F.data.startswith("again:"))
async def repeat_action(callback: CallbackQuery, state: FSMContext):
    action = callback.data.split(":", 1)[1]
    await callback.answer()
    mapping = {
        "income": start_income_flow,
        "expense": start_expense_flow,
        "goal": start_goal_flow,
        "debt": start_debt_flow,
        "recurring": start_recurring_flow,
        "fund": start_fund_flow,
    }
    await mapping[action](callback.message, state)


@router.message(F.text.in_({"💰 Доход", "🔁 Еще доход"}))
async def income_start(message: Message, state: FSMContext):
    await start_income_flow(message, state)


@router.message(F.text.in_({"💸 Расход", "🔁 Еще расход"}))
async def expense_start(message: Message, state: FSMContext):
    await start_expense_flow(message, state)


@router.message(F.text.in_({"🎯 Цель", "🔁 Еще цель"}))
async def goal_start(message: Message, state: FSMContext):
    await start_goal_flow(message, state)


@router.message(F.text.in_({"💳 Долг", "🔁 Еще долг"}))
async def debt_start(message: Message, state: FSMContext):
    await start_debt_flow(message, state)


@router.message(F.text.in_({"🔁 Автоплатеж", "🔁 Еще автоплатеж"}))
async def recurring_start(message: Message, state: FSMContext):
    await start_recurring_flow(message, state)


@router.message(F.text.in_({"🏦 Фонд", "🔁 Еще фонд"}))
async def fund_start(message: Message, state: FSMContext):
    await start_fund_flow(message, state)


@router.message(AddIncomeFlow.waiting_amount)
async def income_amount(message: Message, state: FSMContext):
    await remember_user_message(state, message.message_id)
    try:
        amount = parse_amount(message.text)
        if amount <= 0:
            await send_tracked(message, state, "❌ Сумма должна быть больше 0", reply_markup=cancel_menu())
            return
        await state.update_data(amount=amount)
        await state.set_state(AddIncomeFlow.waiting_comment)
        sent = await message.answer("Комментарий или кнопка ниже:", reply_markup=skip_comment_inline("income"))
        await remember_prompt(state, sent.message_id)
    except ValueError:
        await send_tracked(message, state, "❌ Введите сумму числом", reply_markup=cancel_menu())


@router.callback_query(AddIncomeFlow.waiting_comment, F.data == "income:skip_comment")
async def income_skip_comment(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    await add_operation(callback.from_user.id, "income", data["amount"], "Доход", "")
    balance = await get_balance(callback.from_user.id)
    await cleanup_flow_messages(callback.message.chat.id, state)
    await state.clear()
    await callback.message.answer(
        await operation_card(callback.from_user.id, "income", data["amount"], balance=balance),
        reply_markup=repeat_menu("income"),
    )
    await callback.message.answer("Быстрые действия:", reply_markup=quick_after_action_inline("income"))
    await callback.answer()


@router.message(AddIncomeFlow.waiting_comment)
async def income_comment(message: Message, state: FSMContext):
    await remember_user_message(state, message.message_id)
    data = await state.get_data()
    comment = "" if message.text.strip() in {"Без комментария", "-"} else message.text.strip()
    await add_operation(message.from_user.id, "income", data["amount"], "Доход", comment)
    balance = await get_balance(message.from_user.id)
    await cleanup_flow_messages(message.chat.id, state)
    await state.clear()
    await message.answer(
        await operation_card(message.from_user.id, "income", data["amount"], balance=balance),
        reply_markup=repeat_menu("income"),
    )
    await message.answer("Быстрые действия:", reply_markup=quick_after_action_inline("income"))


@router.message(AddExpenseFlow.waiting_amount)
async def expense_amount(message: Message, state: FSMContext):
    await remember_user_message(state, message.message_id)
    try:
        amount = parse_amount(message.text)
        if amount <= 0:
            await send_tracked(message, state, "❌ Сумма должна быть больше 0", reply_markup=cancel_menu())
            return
        await state.update_data(amount=amount)
        await state.set_state(AddExpenseFlow.waiting_category)
        sent = await message.answer("Выберите категорию:", reply_markup=expense_categories_inline())
        await remember_prompt(state, sent.message_id)
    except ValueError:
        await send_tracked(message, state, "❌ Введите сумму числом", reply_markup=cancel_menu())


@router.callback_query(AddExpenseFlow.waiting_category, F.data.startswith("cat:"))
async def expense_category(callback: CallbackQuery, state: FSMContext):
    category_key = callback.data.split(":", 1)[1]
    category = EXPENSE_CATEGORY_MAP.get(category_key)
    if not category:
        await callback.answer("Неизвестная категория", show_alert=True)
        return
    await state.update_data(category=category)
    await state.set_state(AddExpenseFlow.waiting_comment)
    sent = await callback.message.answer("Комментарий или кнопка ниже:", reply_markup=skip_comment_inline("expense"))
    await remember_prompt(state, sent.message_id)
    await callback.answer()


@router.callback_query(AddExpenseFlow.waiting_comment, F.data == "expense:skip_comment")
async def expense_skip_comment(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    await add_operation(callback.from_user.id, "expense", data["amount"], data["category"], "")
    balance = await get_balance(callback.from_user.id)
    await cleanup_flow_messages(callback.message.chat.id, state)
    await state.clear()
    await callback.message.answer(
        await operation_card(
            callback.from_user.id,
            "expense",
            data["amount"],
            category=data["category"],
            balance=balance,
        ),
        reply_markup=repeat_menu("expense"),
    )
    await callback.message.answer("Быстрые действия:", reply_markup=quick_after_action_inline("expense"))
    await callback.answer()


@router.message(AddExpenseFlow.waiting_comment)
async def expense_comment(message: Message, state: FSMContext):
    await remember_user_message(state, message.message_id)
    data = await state.get_data()
    comment = "" if message.text.strip() in {"Без комментария", "-"} else message.text.strip()
    await add_operation(message.from_user.id, "expense", data["amount"], data["category"], comment)
    balance = await get_balance(message.from_user.id)
    await cleanup_flow_messages(message.chat.id, state)
    await state.clear()
    await message.answer(
        await operation_card(
            message.from_user.id,
            "expense",
            data["amount"],
            category=data["category"],
            balance=balance,
        ),
        reply_markup=repeat_menu("expense"),
    )
    await message.answer("Быстрые действия:", reply_markup=quick_after_action_inline("expense"))


@router.message(GoalFlow.waiting_name)
async def goal_name(message: Message, state: FSMContext):
    await remember_user_message(state, message.message_id)
    name = message.text.strip()
    if len(name) < 2:
        await send_tracked(message, state, "❌ Слишком короткое название", reply_markup=cancel_menu())
        return
    await state.update_data(name=name)
    await state.set_state(GoalFlow.waiting_amount)
    await send_tracked(message, state, "Целевая сумма:", reply_markup=cancel_menu())


@router.message(GoalFlow.waiting_amount)
async def goal_amount(message: Message, state: FSMContext):
    await remember_user_message(state, message.message_id)
    try:
        amount = parse_amount(message.text)
        if amount <= 0:
            await send_tracked(message, state, "❌ Сумма должна быть больше 0", reply_markup=cancel_menu())
            return
        data = await state.get_data()
        await add_goal(message.from_user.id, data["name"], amount)
        await cleanup_flow_messages(message.chat.id, state)
        await state.clear()
        await message.answer(
            await operation_card(message.from_user.id, "goal", amount, name=data["name"]),
            reply_markup=repeat_menu("goal"),
        )
        await message.answer("Быстрые действия:", reply_markup=quick_after_action_inline("goal"))
    except ValueError:
        await send_tracked(message, state, "❌ Введите сумму числом", reply_markup=cancel_menu())


@router.message(DebtFlow.waiting_name)
async def debt_name(message: Message, state: FSMContext):
    await remember_user_message(state, message.message_id)
    name = message.text.strip()
    if len(name) < 2:
        await send_tracked(message, state, "❌ Слишком короткое название", reply_markup=cancel_menu())
        return
    await state.update_data(name=name)
    await state.set_state(DebtFlow.waiting_amount)
    await send_tracked(message, state, "Сумма долга:", reply_markup=cancel_menu())


@router.message(DebtFlow.waiting_amount)
async def debt_amount(message: Message, state: FSMContext):
    await remember_user_message(state, message.message_id)
    try:
        amount = parse_amount(message.text)
        if amount <= 0:
            await send_tracked(message, state, "❌ Сумма должна быть больше 0", reply_markup=cancel_menu())
            return
        data = await state.get_data()
        await add_debt(message.from_user.id, data["name"], amount)
        await cleanup_flow_messages(message.chat.id, state)
        await state.clear()
        await message.answer(
            await operation_card(message.from_user.id, "debt", amount, name=data["name"]),
            reply_markup=repeat_menu("debt"),
        )
        await message.answer("Быстрые действия:", reply_markup=quick_after_action_inline("debt"))
    except ValueError:
        await send_tracked(message, state, "❌ Введите сумму числом", reply_markup=cancel_menu())


@router.message(RecurringFlow.waiting_name)
async def recurring_name(message: Message, state: FSMContext):
    await remember_user_message(state, message.message_id)
    name = message.text.strip()
    if len(name) < 2:
        await send_tracked(message, state, "❌ Слишком короткое название", reply_markup=cancel_menu())
        return
    await state.update_data(name=name)
    await state.set_state(RecurringFlow.waiting_amount)
    await send_tracked(message, state, "Сумма в месяц:", reply_markup=cancel_menu())


@router.message(RecurringFlow.waiting_amount)
async def recurring_amount(message: Message, state: FSMContext):
    await remember_user_message(state, message.message_id)
    try:
        amount = parse_amount(message.text)
        if amount <= 0:
            await send_tracked(message, state, "❌ Сумма должна быть больше 0", reply_markup=cancel_menu())
            return
        data = await state.get_data()
        await add_recurring(message.from_user.id, data["name"], amount)
        await cleanup_flow_messages(message.chat.id, state)
        await state.clear()
        await message.answer(
            await operation_card(message.from_user.id, "recurring", amount, name=data["name"]),
            reply_markup=repeat_menu("recurring"),
        )
        await message.answer("Быстрые действия:", reply_markup=quick_after_action_inline("recurring"))
    except ValueError:
        await send_tracked(message, state, "❌ Введите сумму числом", reply_markup=cancel_menu())


@router.message(FundFlow.waiting_name)
async def fund_name(message: Message, state: FSMContext):
    await remember_user_message(state, message.message_id)
    name = message.text.strip()
    if len(name) < 2:
        await send_tracked(message, state, "❌ Слишком короткое название", reply_markup=cancel_menu())
        return
    await state.update_data(name=name)
    await state.set_state(FundFlow.waiting_target)
    await send_tracked(message, state, "Целевая сумма фонда:", reply_markup=cancel_menu())


@router.message(FundFlow.waiting_target)
async def fund_target(message: Message, state: FSMContext):
    await remember_user_message(state, message.message_id)
    try:
        amount = parse_amount(message.text)
        if amount <= 0:
            await send_tracked(message, state, "❌ Сумма должна быть больше 0", reply_markup=cancel_menu())
            return
        await state.update_data(target_amount=amount)
        await state.set_state(FundFlow.waiting_monthly)
        await send_tracked(message, state, "Ежемесячный взнос (можно 0):", reply_markup=cancel_menu())
    except ValueError:
        await send_tracked(message, state, "❌ Введите сумму числом", reply_markup=cancel_menu())


@router.message(FundFlow.waiting_monthly)
async def fund_monthly(message: Message, state: FSMContext):
    await remember_user_message(state, message.message_id)
    try:
        monthly = parse_amount(message.text)
        if monthly < 0:
            await send_tracked(message, state, "❌ Сумма не может быть отрицательной", reply_markup=cancel_menu())
            return
        data = await state.get_data()
        await add_fund(message.from_user.id, data["name"], data["target_amount"], monthly)
        await cleanup_flow_messages(message.chat.id, state)
        await state.clear()
        await message.answer(
            await operation_card(message.from_user.id, "fund", data["target_amount"], name=data["name"]),
            reply_markup=repeat_menu("fund"),
        )
        await message.answer("Быстрые действия:", reply_markup=quick_after_action_inline("fund"))
    except ValueError:
        await send_tracked(message, state, "❌ Введите сумму числом", reply_markup=cancel_menu())


@router.message(F.text == "📊 Бюджет")
async def budget_start(message: Message, state: FSMContext):
    await start_budget_flow(message, state)


@router.message(BudgetFlow.waiting_salary)
async def budget_salary(message: Message, state: FSMContext):
    await remember_user_message(state, message.message_id)
    try:
        salary = parse_amount(message.text)
        if salary <= 0:
            await send_tracked(message, state, "❌ Доход должен быть больше 0", reply_markup=cancel_menu())
            return
        await state.update_data(salary=salary)
        await state.set_state(BudgetFlow.waiting_rent)
        await send_tracked(message, state, "Шаг 2/3 — аренда:", reply_markup=cancel_menu())
    except ValueError:
        await send_tracked(message, state, "❌ Введите сумму числом", reply_markup=cancel_menu())


@router.message(BudgetFlow.waiting_rent)
async def budget_rent(message: Message, state: FSMContext):
    await remember_user_message(state, message.message_id)
    try:
        rent = parse_amount(message.text)
        if rent < 0:
            await send_tracked(message, state, "❌ Сумма не может быть отрицательной", reply_markup=cancel_menu())
            return
        await state.update_data(rent=rent)
        await state.set_state(BudgetFlow.waiting_utilities)
        await send_tracked(message, state, "Шаг 3/3 — коммуналка:", reply_markup=cancel_menu())
    except ValueError:
        await send_tracked(message, state, "❌ Введите сумму числом", reply_markup=cancel_menu())


@router.message(BudgetFlow.waiting_utilities)
async def budget_utilities(message: Message, state: FSMContext):
    await remember_user_message(state, message.message_id)
    try:
        utilities = parse_amount(message.text)
        if utilities < 0:
            await send_tracked(message, state, "❌ Сумма не может быть отрицательной", reply_markup=cancel_menu())
            return

        data = await state.get_data()
        result = calculate_auto_budget(data["salary"], data["rent"], utilities)
        if result is None:
            await send_tracked(message, state, "❌ Fixed-расходы больше дохода", reply_markup=cancel_menu())
            return

        await state.update_data(preview_budget=result)
        await state.set_state(BudgetFlow.preview_distribution)
        await cleanup_flow_messages(message.chat.id, state)
        sent = await message.answer(
            await build_budget_preview_text(message.from_user.id, result),
            reply_markup=budget_preview_inline(),
        )
        await remember_prompt(state, sent.message_id)
    except ValueError:
        await send_tracked(message, state, "❌ Введите сумму числом", reply_markup=cancel_menu())


@router.callback_query(BudgetFlow.preview_distribution, F.data == "budget:edit")
async def budget_edit_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(BudgetFlow.editing_distribution)
    sent = await callback.message.answer(
        "Выберите категорию для редактирования, потом введите новую сумму.",
        reply_markup=budget_edit_inline(),
    )
    await remember_prompt(state, sent.message_id)
    await callback.answer()


@router.callback_query(BudgetFlow.editing_distribution, F.data.startswith("budget_edit:"))
async def budget_edit_pick(callback: CallbackQuery, state: FSMContext):
    category = callback.data.split(":", 1)[1]
    await state.update_data(edit_category=category)
    sent = await callback.message.answer(f"Введите новую сумму для «{category}»:", reply_markup=cancel_menu())
    await remember_prompt(state, sent.message_id)
    await callback.answer()


@router.message(BudgetFlow.editing_distribution)
async def budget_edit_amount(message: Message, state: FSMContext):
    await remember_user_message(state, message.message_id)
    data = await state.get_data()
    category = data.get("edit_category")
    if not category:
        await send_tracked(message, state, "❌ Сначала выберите категорию кнопкой", reply_markup=cancel_menu())
        return

    try:
        new_amount = parse_amount(message.text)
        if new_amount < 0:
            await send_tracked(message, state, "❌ Сумма не может быть отрицательной", reply_markup=cancel_menu())
            return

        preview = data["preview_budget"]
        preview["auto_budget"][category] = round(new_amount, 2)
        distributed_sum = round(sum(preview["auto_budget"].values()), 2)

        if distributed_sum > round(preview["remaining"], 2):
            await send_tracked(
                message,
                state,
                f"❌ Распределение больше остатка: {await money(message.from_user.id, distributed_sum)} > {await money(message.from_user.id, preview['remaining'])}",
                reply_markup=cancel_menu(),
            )
            return

        await state.update_data(preview_budget=preview, edit_category=None)
        await state.set_state(BudgetFlow.confirm_distribution)
        sent = await message.answer(
            await build_budget_preview_text(message.from_user.id, preview),
            reply_markup=budget_confirm_inline(),
        )
        await remember_prompt(state, sent.message_id)
    except ValueError:
        await send_tracked(message, state, "❌ Введите сумму числом", reply_markup=cancel_menu())


@router.callback_query(F.data == "budget:confirm")
async def budget_confirm(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    preview = data.get("preview_budget")
    if not preview:
        await callback.answer("Нет данных бюджета", show_alert=True)
        return

    await state.set_state(BudgetFlow.confirm_distribution)
    sent = await callback.message.answer(
        await build_budget_preview_text(callback.from_user.id, preview),
        reply_markup=budget_confirm_inline(),
    )
    await remember_prompt(state, sent.message_id)
    await callback.answer()


@router.callback_query(F.data == "budget:recalc")
async def budget_recalc(callback: CallbackQuery, state: FSMContext):
    await cleanup_flow_messages(callback.message.chat.id, state)
    await state.set_state(BudgetFlow.waiting_salary)
    sent = await callback.message.answer("Шаг 1/3 — введите новый доход:", reply_markup=cancel_menu())
    await remember_prompt(state, sent.message_id)
    await callback.answer()


@router.callback_query(F.data == "budget:save")
async def budget_save(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    preview = data.get("preview_budget")
    if not preview:
        await callback.answer("Нет данных бюджета", show_alert=True)
        return

    await save_budget(
        callback.from_user.id,
        get_current_month_key(),
        preview["salary"],
        preview["rent"],
        preview["utilities"],
        preview["fixed_total"],
        preview["remaining"],
        preview["auto_budget"],
    )

    await cleanup_flow_messages(callback.message.chat.id, state)
    await state.clear()
    await callback.message.answer("✅ Бюджет сохранен", reply_markup=root_menu())
    await callback.message.answer(
        await build_budget_preview_text(callback.from_user.id, preview),
        reply_markup=home_inline(),
    )
    await callback.answer()


@router.message(F.text == "💼 Баланс")
async def balance_button(message: Message):
    balance = await get_balance(message.from_user.id)
    await message.answer(
        f"💼 Баланс\n{await money(message.from_user.id, balance)}",
        reply_markup=more_menu(),
    )


@router.message(F.text == "📅 Сегодня")
async def today_button(message: Message):
    operations = await get_period_operations(message.from_user.id, 1)
    today = datetime.now().date()
    items = [op for op in operations if op.created_at.date() == today]
    if not items:
        await message.answer("📅 Сегодня пусто", reply_markup=more_menu())
        return

    income, expense, total = summarize_operations(items)
    await message.answer(
        f"📅 Сегодня\n"
        f"Доходы: {await money(message.from_user.id, income)}\n"
        f"Расходы: {await money(message.from_user.id, expense)}\n"
        f"Итог: {await money(message.from_user.id, total)}",
        reply_markup=more_menu(),
    )


@router.message(F.text == "📆 Неделя")
async def week_button(message: Message):
    operations = await get_period_operations(message.from_user.id, 7)
    if not operations:
        await message.answer("📆 За неделю пусто", reply_markup=more_menu())
        return

    income, expense, total = summarize_operations(operations)
    await message.answer(
        f"📆 Неделя\n"
        f"Доходы: {await money(message.from_user.id, income)}\n"
        f"Расходы: {await money(message.from_user.id, expense)}\n"
        f"Итог: {await money(message.from_user.id, total)}",
        reply_markup=more_menu(),
    )


@router.message(F.text == "🗓 Месяц")
async def month_button(message: Message):
    operations = await get_period_operations(message.from_user.id, 30)
    if not operations:
        await message.answer("🗓 За месяц пусто", reply_markup=more_menu())
        return

    income, expense, total = summarize_operations(operations)
    await message.answer(
        f"🗓 Месяц\n"
        f"Доходы: {await money(message.from_user.id, income)}\n"
        f"Расходы: {await money(message.from_user.id, expense)}\n"
        f"Итог: {await money(message.from_user.id, total)}",
        reply_markup=more_menu(),
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
        f"Баланс: {await money(message.from_user.id, balance)}\n"
        f"Неделя: +{await money(message.from_user.id, week_income)} / -{await money(message.from_user.id, week_expense)}\n"
        f"Месяц: +{await money(message.from_user.id, month_income)} / -{await money(message.from_user.id, month_expense)}"
    )
    if current_budget:
        text += f"\nЛимит недели: {await money(message.from_user.id, current_budget.remaining / 4)}"

    await message.answer(text, reply_markup=root_menu())


@router.message(F.text == "📜 История")
async def history_button(message: Message):
    operations = await get_recent_operations(message.from_user.id)
    if not operations:
        await message.answer("📜 История пуста", reply_markup=root_menu())
        return

    text = "📜 Последние операции:\n\n"
    for op in operations[:10]:
        emoji = "💰" if op.type == "income" else "💸"
        text += f"{emoji} {await money(message.from_user.id, op.amount)} · {op.category} · {op.created_at.strftime('%d.%m %H:%M')}\n"

    await message.answer(text, reply_markup=root_menu())


@router.message(F.text == "📂 Бюджет месяца")
async def budget_month_button(message: Message):
    budget = await get_budget_by_month(message.from_user.id, get_current_month_key())
    if not budget:
        await message.answer("📂 Бюджет не создан\nСоздайте его через «📊 Бюджет»", reply_markup=more_menu())
        return
    await message.answer(await build_budget_from_db(message.from_user.id, budget), reply_markup=more_menu())


@router.message(F.text == "📚 Архив бюджетов")
async def archive_button(message: Message):
    budgets = await get_budget_archive(message.from_user.id)
    if not budgets:
        await message.answer("📚 Архив пуст", reply_markup=more_menu())
        return

    text = "📚 Архив бюджетов:\n\n"
    for budget in budgets:
        text += f"{budget.month_key}: {await money(message.from_user.id, budget.salary)} / fixed {await money(message.from_user.id, budget.fixed_total)} / остаток {await money(message.from_user.id, budget.remaining)}\n"

    await message.answer(text, reply_markup=more_menu())


@router.message(F.text == "🎯 Цели")
async def goals_button(message: Message):
    goals = await get_goals(message.from_user.id)
    if not goals:
        await message.answer(
            "🎯 Целей пока нет\nДобавьте первую через «➕ Добавить» → «🎯 Цель»",
            reply_markup=more_menu(),
        )
        return

    text = "🎯 Цели:\n\n"
    for goal in goals:
        progress = (goal.current / goal.target * 100) if goal.target else 0
        text += f"{goal.name}: {await money(message.from_user.id, goal.current)}/{await money(message.from_user.id, goal.target)} ({progress:.1f}%)\n"

    await message.answer(text, reply_markup=more_menu())


@router.message(F.text == "💳 Долги")
async def debts_button(message: Message):
    debts = await get_debts(message.from_user.id)
    if not debts:
        await message.answer(
            "💳 Долгов пока нет\nДобавьте первый через «➕ Добавить» → «💳 Долг»",
            reply_markup=more_menu(),
        )
        return

    total = sum(item.amount for item in debts)
    text = "💳 Долги:\n\n"
    for item in debts:
        text += f"{item.name}: {await money(message.from_user.id, item.amount)}\n"
    text += f"\nИтого: {await money(message.from_user.id, total)}"

    await message.answer(text, reply_markup=more_menu())


@router.message(F.text == "🔁 Автоплатежи")
async def recurring_button(message: Message):
    recurring = await get_recurring(message.from_user.id)
    if not recurring:
        await message.answer(
            "🔁 Автоплатежей нет\nДобавьте первый через «➕ Добавить» → «🔁 Автоплатеж»",
            reply_markup=more_menu(),
        )
        return

    total = sum(item.amount for item in recurring)
    text = "🔁 Автоплатежи:\n\n"
    for item in recurring:
        text += f"{item.name}: {await money(message.from_user.id, item.amount)}/мес\n"
    text += f"\nИтого: {await money(message.from_user.id, total)}/мес"

    await message.answer(text, reply_markup=more_menu())


@router.message(F.text == "🏦 Фонды")
async def funds_button(message: Message):
    funds = await get_funds(message.from_user.id)
    if not funds:
        await message.answer(
            "🏦 Фондов пока нет\nДобавьте первый через «➕ Добавить» → «🏦 Фонд»",
            reply_markup=more_menu(),
        )
        return

    text = "🏦 Фонды:\n\n"
    for fund in funds:
        progress = (fund.current_amount / fund.target_amount * 100) if fund.target_amount else 0
        text += f"{fund.name}: {await money(message.from_user.id, fund.current_amount)}/{await money(message.from_user.id, fund.target_amount)} ({progress:.1f}%)\n"

    await message.answer(text, reply_markup=more_menu())


@router.message(F.text == "⚙️ Настройки")
async def settings_button(message: Message, state: FSMContext):
    user = await get_or_create_user(message.from_user.id)
    await state.set_state(SettingsFlow.viewing)
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


@router.callback_query(F.data == "settings:toggle_reminders")
async def settings_toggle_reminders(callback: CallbackQuery):
    user = await get_or_create_user(callback.from_user.id)
    updated = await update_user_settings(callback.from_user.id, reminders_enabled=not user.reminders_enabled)
    await callback.message.answer(
        f"✅ Напоминания: {'ON' if updated.reminders_enabled else 'OFF'}",
        reply_markup=settings_inline(updated),
    )
    await callback.answer()


@router.callback_query(F.data == "settings:currency")
async def settings_currency(callback: CallbackQuery):
    await callback.message.answer("Выберите валюту:", reply_markup=settings_currency_inline())
    await callback.answer()


@router.callback_query(F.data.startswith("settings_currency:"))
async def settings_currency_apply(callback: CallbackQuery):
    code = callback.data.split(":", 1)[1]
    updated = await update_user_settings(callback.from_user.id, currency=code)
    await callback.message.answer(f"✅ Валюта: {updated.default_currency}", reply_markup=settings_inline(updated))
    await callback.answer()


@router.callback_query(F.data == "settings:language")
async def settings_language(callback: CallbackQuery):
    await callback.message.answer("Выберите язык:", reply_markup=settings_language_inline())
    await callback.answer()


@router.callback_query(F.data.startswith("settings_language:"))
async def settings_language_apply(callback: CallbackQuery):
    code = callback.data.split(":", 1)[1]
    updated = await update_user_settings(callback.from_user.id, language=code)
    await callback.message.answer(f"✅ Язык: {updated.language}", reply_markup=settings_inline(updated))
    await callback.answer()


@router.callback_query(F.data == "settings:time")
async def settings_time(callback: CallbackQuery):
    await callback.message.answer("Выберите время уведомлений:", reply_markup=settings_time_inline())
    await callback.answer()


@router.callback_query(F.data.startswith("settings_time:"))
async def settings_time_apply(callback: CallbackQuery):
    value = callback.data.split(":", 1)[1]
    updated = await update_user_settings(callback.from_user.id, notification_time=value)
    await callback.message.answer(
        f"✅ Время уведомлений: {updated.notification_time}",
        reply_markup=settings_inline(updated),
    )
    await callback.answer()


@router.message()
async def fallback_handler(message: Message):
    await message.answer("Используйте кнопки меню.", reply_markup=root_menu())


async def main():
    await init_db()
    dp.include_router(router)
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
