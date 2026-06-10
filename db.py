import os
from datetime import datetime, timedelta

from dotenv import load_dotenv
from sqlalchemy import String, Float, Integer, DateTime, ForeignKey, select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///finance_bot.db")

engine = create_async_engine(DATABASE_URL, echo=False)
async_session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Operation(Base):
    __tablename__ = "operations"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(Integer, index=True)
    type: Mapped[str] = mapped_column(String(20))
    amount: Mapped[float] = mapped_column(Float)
    category: Mapped[str] = mapped_column(String(100))
    comment: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Budget(Base):
    __tablename__ = "budgets"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(Integer, index=True)
    month_key: Mapped[str] = mapped_column(String(7), index=True)
    salary: Mapped[float] = mapped_column(Float)
    rent: Mapped[float] = mapped_column(Float)
    utilities: Mapped[float] = mapped_column(Float)
    fixed_total: Mapped[float] = mapped_column(Float)
    remaining: Mapped[float] = mapped_column(Float)
    food: Mapped[float] = mapped_column(Float)
    transport: Mapped[float] = mapped_column(Float)
    savings: Mapped[float] = mapped_column(Float)
    entertainment: Mapped[float] = mapped_column(Float)
    health: Mapped[float] = mapped_column(Float)
    other: Mapped[float] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Goal(Base):
    __tablename__ = "goals"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(Integer, index=True)
    name: Mapped[str] = mapped_column(String(100))
    target: Mapped[float] = mapped_column(Float)
    current: Mapped[float] = mapped_column(Float, default=0.0)


class Debt(Base):
    __tablename__ = "debts"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(Integer, index=True)
    name: Mapped[str] = mapped_column(String(100))
    amount: Mapped[float] = mapped_column(Float)


class RecurringPayment(Base):
    __tablename__ = "recurring_payments"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(Integer, index=True)
    name: Mapped[str] = mapped_column(String(100))
    amount: Mapped[float] = mapped_column(Float)


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_or_create_user(telegram_id: int):
    async with async_session() as session:
        result = await session.execute(select(User).where(User.telegram_id == telegram_id))
        user = result.scalar_one_or_none()

        if user is None:
            user = User(telegram_id=telegram_id)
            session.add(user)
            await session.commit()

        return user


async def add_operation(telegram_id: int, op_type: str, amount: float, category: str, comment: str = ""):
    async with async_session() as session:
        op = Operation(
            telegram_id=telegram_id,
            type=op_type,
            amount=amount,
            category=category,
            comment=comment,
        )
        session.add(op)
        await session.commit()


async def get_balance(telegram_id: int) -> float:
    async with async_session() as session:
        result = await session.execute(select(Operation).where(Operation.telegram_id == telegram_id))
        operations = result.scalars().all()

        balance = 0.0
        for op in operations:
            if op.type == "income":
                balance += op.amount
            else:
                balance -= op.amount

        return balance


async def get_recent_operations(telegram_id: int, limit: int = 10):
    async with async_session() as session:
        result = await session.execute(
            select(Operation)
            .where(Operation.telegram_id == telegram_id)
            .order_by(Operation.created_at.desc())
        )
        return result.scalars().all()[:limit]


async def get_period_operations(telegram_id: int, days: int):
    async with async_session() as session:
        date_from = datetime.utcnow() - timedelta(days=days)
        result = await session.execute(
            select(Operation)
            .where(Operation.telegram_id == telegram_id)
            .where(Operation.created_at >= date_from)
            .order_by(Operation.created_at.desc())
        )
        return result.scalars().all()


async def save_budget(telegram_id: int, month_key: str, salary: float, rent: float, utilities: float,
                      fixed_total: float, remaining: float, auto_budget: dict):
    async with async_session() as session:
        result = await session.execute(
            select(Budget)
            .where(Budget.telegram_id == telegram_id)
            .where(Budget.month_key == month_key)
        )
        old_budget = result.scalar_one_or_none()

        if old_budget:
            await session.delete(old_budget)
            await session.commit()

        budget = Budget(
            telegram_id=telegram_id,
            month_key=month_key,
            salary=salary,
            rent=rent,
            utilities=utilities,
            fixed_total=fixed_total,
            remaining=remaining,
            food=auto_budget.get("Еда", 0.0),
            transport=auto_budget.get("Транспорт", 0.0),
            savings=auto_budget.get("Накопления", 0.0),
            entertainment=auto_budget.get("Развлечения", 0.0),
            health=auto_budget.get("Здоровье", 0.0),
            other=auto_budget.get("Прочее", 0.0),
        )
        session.add(budget)
        await session.commit()


async def get_budget_by_month(telegram_id: int, month_key: str):
    async with async_session() as session:
        result = await session.execute(
            select(Budget)
            .where(Budget.telegram_id == telegram_id)
            .where(Budget.month_key == month_key)
        )
        return result.scalar_one_or_none()


async def get_budget_archive(telegram_id: int):
    async with async_session() as session:
        result = await session.execute(
            select(Budget)
            .where(Budget.telegram_id == telegram_id)
            .order_by(Budget.month_key.desc())
        )
        return result.scalars().all()


async def add_goal(telegram_id: int, name: str, target: float):
    async with async_session() as session:
        session.add(Goal(telegram_id=telegram_id, name=name, target=target, current=0.0))
        await session.commit()


async def get_goals(telegram_id: int):
    async with async_session() as session:
        result = await session.execute(select(Goal).where(Goal.telegram_id == telegram_id))
        return result.scalars().all()


async def add_debt(telegram_id: int, name: str, amount: float):
    async with async_session() as session:
        session.add(Debt(telegram_id=telegram_id, name=name, amount=amount))
        await session.commit()


async def get_debts(telegram_id: int):
    async with async_session() as session:
        result = await session.execute(select(Debt).where(Debt.telegram_id == telegram_id))
        return result.scalars().all()


async def add_recurring(telegram_id: int, name: str, amount: float):
    async with async_session() as session:
        session.add(RecurringPayment(telegram_id=telegram_id, name=name, amount=amount))
        await session.commit()


async def get_recurring(telegram_id: int):
    async with async_session() as session:
        result = await session.execute(
            select(RecurringPayment).where(RecurringPayment.telegram_id == telegram_id)
        )
        return result.scalars().all()
