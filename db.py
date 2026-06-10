import os
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///finance.db")

engine = create_async_engine(DATABASE_URL, future=True, echo=False)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    name: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    timezone: Mapped[str] = mapped_column(String, default="Europe/Moscow")
    default_currency: Mapped[str] = mapped_column(String, default="RUB")
    language: Mapped[str] = mapped_column(String, default="ru")
    notification_time: Mapped[str] = mapped_column(String, default="09:00")
    reminders_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String)
    type: Mapped[str] = mapped_column(String, default="cash")
    currency: Mapped[str] = mapped_column(String, default="RUB")
    initial_balance: Mapped[float] = mapped_column(Float, default=0)
    current_balance: Mapped[float] = mapped_column(Float, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Category(Base):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String)
    type: Mapped[str] = mapped_column(String, default="expense")
    parent_category: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    alias: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    emoji: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Operation(Base):
    __tablename__ = "operations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    account_id: Mapped[Optional[int]] = mapped_column(ForeignKey("accounts.id"), nullable=True)
    category_id: Mapped[Optional[int]] = mapped_column(ForeignKey("categories.id"), nullable=True)
    type: Mapped[str] = mapped_column(String)
    amount: Mapped[float] = mapped_column(Float)
    currency: Mapped[str] = mapped_column(String, default="RUB")
    category: Mapped[str] = mapped_column(String)
    comment: Mapped[str] = mapped_column(String, default="")
    source: Mapped[str] = mapped_column(String, default="manual")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Budget(Base):
    __tablename__ = "budgets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    month_key: Mapped[str] = mapped_column(String, index=True)
    salary: Mapped[float] = mapped_column(Float)
    rent: Mapped[float] = mapped_column(Float, default=0)
    utilities: Mapped[float] = mapped_column(Float, default=0)
    fixed_total: Mapped[float] = mapped_column(Float, default=0)
    remaining: Mapped[float] = mapped_column(Float, default=0)
    food: Mapped[float] = mapped_column(Float, default=0)
    transport: Mapped[float] = mapped_column(Float, default=0)
    savings: Mapped[float] = mapped_column(Float, default=0)
    entertainment: Mapped[float] = mapped_column(Float, default=0)
    health: Mapped[float] = mapped_column(Float, default=0)
    other: Mapped[float] = mapped_column(Float, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Goal(Base):
    __tablename__ = "goals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String)
    target: Mapped[float] = mapped_column(Float)
    current: Mapped[float] = mapped_column(Float, default=0)
    deadline: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Debt(Base):
    __tablename__ = "debts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String)
    amount: Mapped[float] = mapped_column(Float)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class RecurringPayment(Base):
    __tablename__ = "recurring_payments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String)
    amount: Mapped[float] = mapped_column(Float)
    period: Mapped[str] = mapped_column(String, default="monthly")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Fund(Base):
    __tablename__ = "funds"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String)
    target_amount: Mapped[float] = mapped_column(Float, default=0)
    current_amount: Mapped[float] = mapped_column(Float, default=0)
    monthly_contribution: Mapped[float] = mapped_column(Float, default=0)
    deadline: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Reminder(Base):
    __tablename__ = "reminders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    type: Mapped[str] = mapped_column(String)
    time: Mapped[str] = mapped_column(String, default="09:00")
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)


DEFAULT_EXPENSE_CATEGORIES = [
    ("Еда", "expense", "🍔"),
    ("Транспорт", "expense", "🚌"),
    ("Развлечения", "expense", "🎉"),
    ("Здоровье", "expense", "💊"),
    ("Прочее", "expense", "🧾"),
]
DEFAULT_INCOME_CATEGORIES = [
    ("Доход", "income", "💰"),
]


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_or_create_user(telegram_id: int, name: str | None = None):
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(User).where(User.telegram_id == telegram_id))
        user = result.scalar_one_or_none()
        if user:
            if name and user.name != name:
                user.name = name
                await session.commit()
            return user

        user = User(telegram_id=telegram_id, name=name)
        session.add(user)
        await session.flush()

        session.add(
            Account(
                user_id=user.id,
                name="Основной",
                type="cash",
                currency="RUB",
                initial_balance=0,
                current_balance=0,
                is_active=True,
            )
        )

        for name_, type_, emoji in DEFAULT_EXPENSE_CATEGORIES + DEFAULT_INCOME_CATEGORIES:
            session.add(Category(user_id=user.id, name=name_, type=type_, emoji=emoji, is_active=True))

        await session.commit()
        return user


async def get_user_by_telegram_id(telegram_id: int):
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(User).where(User.telegram_id == telegram_id))
        return result.scalar_one_or_none()


async def add_operation(telegram_id: int, type: str, amount: float, category: str, comment: str = ""):
    user = await get_or_create_user(telegram_id)
    async with AsyncSessionLocal() as session:
        account_result = await session.execute(
            select(Account).where(Account.user_id == user.id, Account.is_active == True).order_by(Account.id.asc())
        )
        account = account_result.scalars().first()

        category_result = await session.execute(
            select(Category).where(Category.user_id == user.id, Category.name == category, Category.is_active == True)
        )
        category_obj = category_result.scalar_one_or_none()

        operation = Operation(
            user_id=user.id,
            account_id=account.id if account else None,
            category_id=category_obj.id if category_obj else None,
            type=type,
            amount=amount,
            currency=account.currency if account else "RUB",
            category=category,
            comment=comment,
            source="manual",
        )
        session.add(operation)

        if account:
            if type == "income":
                account.current_balance += amount
            else:
                account.current_balance -= amount

        await session.commit()
        return operation


async def get_balance(telegram_id: int) -> float:
    user = await get_or_create_user(telegram_id)
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Account).where(Account.user_id == user.id, Account.is_active == True))
        accounts = result.scalars().all()
        return round(sum(acc.current_balance for acc in accounts), 2)


async def get_recent_operations(telegram_id: int, limit: int = 10):
    user = await get_or_create_user(telegram_id)
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Operation).where(Operation.user_id == user.id).order_by(Operation.created_at.desc()).limit(limit)
        )
        return result.scalars().all()


async def get_period_operations(telegram_id: int, days: int):
    user = await get_or_create_user(telegram_id)
    start_date = datetime.utcnow() - timedelta(days=days)
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Operation)
            .where(Operation.user_id == user.id, Operation.created_at >= start_date)
            .order_by(Operation.created_at.desc())
        )
        return result.scalars().all()


async def save_budget(
    telegram_id: int,
    month_key: str,
    salary: float,
    rent: float,
    utilities: float,
    fixed_total: float,
    remaining: float,
    auto_budget: dict,
):
    user = await get_or_create_user(telegram_id)
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Budget).where(Budget.user_id == user.id, Budget.month_key == month_key))
        budget = result.scalar_one_or_none()
        if budget is None:
            budget = Budget(user_id=user.id, month_key=month_key, salary=salary)
            session.add(budget)

        budget.salary = salary
        budget.rent = rent
        budget.utilities = utilities
        budget.fixed_total = fixed_total
        budget.remaining = remaining
        budget.food = auto_budget.get("Еда", 0)
        budget.transport = auto_budget.get("Транспорт", 0)
        budget.savings = auto_budget.get("Накопления", 0)
        budget.entertainment = auto_budget.get("Развлечения", 0)
        budget.health = auto_budget.get("Здоровье", 0)
        budget.other = auto_budget.get("Прочее", 0)

        await session.commit()
        return budget


async def get_budget_by_month(telegram_id: int, month_key: str):
    user = await get_or_create_user(telegram_id)
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Budget).where(Budget.user_id == user.id, Budget.month_key == month_key))
        return result.scalar_one_or_none()


async def get_budget_archive(telegram_id: int):
    user = await get_or_create_user(telegram_id)
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Budget).where(Budget.user_id == user.id).order_by(Budget.month_key.desc()))
        return result.scalars().all()


async def add_goal(telegram_id: int, name: str, target: float, deadline: str | None = None):
    user = await get_or_create_user(telegram_id)
    async with AsyncSessionLocal() as session:
        goal = Goal(user_id=user.id, name=name, target=target, current=0, deadline=deadline, is_active=True)
        session.add(goal)
        await session.commit()
        return goal


async def get_goals(telegram_id: int):
    user = await get_or_create_user(telegram_id)
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Goal).where(Goal.user_id == user.id, Goal.is_active == True))
        return result.scalars().all()


async def add_debt(telegram_id: int, name: str, amount: float):
    user = await get_or_create_user(telegram_id)
    async with AsyncSessionLocal() as session:
        debt = Debt(user_id=user.id, name=name, amount=amount, is_active=True)
        session.add(debt)
        await session.commit()
        return debt


async def get_debts(telegram_id: int):
    user = await get_or_create_user(telegram_id)
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Debt).where(Debt.user_id == user.id, Debt.is_active == True))
        return result.scalars().all()


async def add_recurring(telegram_id: int, name: str, amount: float, period: str = "monthly"):
    user = await get_or_create_user(telegram_id)
    async with AsyncSessionLocal() as session:
        recurring = RecurringPayment(user_id=user.id, name=name, amount=amount, period=period, is_active=True)
        session.add(recurring)
        await session.commit()
        return recurring


async def get_recurring(telegram_id: int):
    user = await get_or_create_user(telegram_id)
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(RecurringPayment).where(RecurringPayment.user_id == user.id, RecurringPayment.is_active == True)
        )
        return result.scalars().all()


async def add_fund(
    telegram_id: int,
    name: str,
    target_amount: float,
    monthly_contribution: float = 0,
    deadline: str | None = None,
):
    user = await get_or_create_user(telegram_id)
    async with AsyncSessionLocal() as session:
        fund = Fund(
            user_id=user.id,
            name=name,
            target_amount=target_amount,
            current_amount=0,
            monthly_contribution=monthly_contribution,
            deadline=deadline,
            is_active=True,
        )
        session.add(fund)
        await session.commit()
        return fund


async def get_funds(telegram_id: int):
    user = await get_or_create_user(telegram_id)
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Fund).where(Fund.user_id == user.id, Fund.is_active == True))
        return result.scalars().all()


async def update_user_settings(
    telegram_id: int,
    timezone: str | None = None,
    currency: str | None = None,
    language: str | None = None,
    notification_time: str | None = None,
    reminders_enabled: bool | None = None,
):
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(User).where(User.telegram_id == telegram_id))
        user = result.scalar_one_or_none()
        if not user:
            await get_or_create_user(telegram_id)
            result = await session.execute(select(User).where(User.telegram_id == telegram_id))
            user = result.scalar_one_or_none()

        if timezone is not None:
            user.timezone = timezone
        if currency is not None:
            user.default_currency = currency
        if language is not None:
            user.language = language
        if notification_time is not None:
            user.notification_time = notification_time
        if reminders_enabled is not None:
            user.reminders_enabled = reminders_enabled

        await session.commit()
        return user
