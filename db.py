import datetime
import os
from typing import Optional
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy import String, Integer, Float, Boolean, DateTime, ForeignKey, select, func
from dotenv import load_dotenv

load_dotenv()
DB_URL = os.getenv("DB_URL", "sqlite+aiosqlite:///finance_bot.db")

engine = create_async_engine(DB_URL, echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

class Base(DeclarativeBase):
    pass

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tg_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    timezone: Mapped[str] = mapped_column(String(64), default="Europe/Moscow")
    currency: Mapped[str] = mapped_column(String(8), default="₽")
    lang: Mapped[str] = mapped_column(String(8), default="ru")
    daily_report_hour: Mapped[int] = mapped_column(Integer, default=21)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=datetime.datetime.utcnow)
    accounts: Mapped[list["Account"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    categories: Mapped[list["Category"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    operations: Mapped[list["Operation"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    envelopes: Mapped[list["Envelope"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    funds: Mapped[list["Fund"]] = relationship(back_populates="user", cascade="all, delete-orphan")

class Account(Base):
    __tablename__ = "accounts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    name: Mapped[str] = mapped_column(String(255))
    type: Mapped[str] = mapped_column(String(64), default="card")
    currency: Mapped[str] = mapped_column(String(8), default="₽")
    initial_balance: Mapped[float] = mapped_column(Float, default=0.0)
    balance: Mapped[float] = mapped_column(Float, default=0.0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    user: Mapped["User"] = relationship(back_populates="accounts")

class Category(Base):
    __tablename__ = "categories"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    name: Mapped[str] = mapped_column(String(255))
    type: Mapped[str] = mapped_column(String(16))
    emoji: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    user: Mapped["User"] = relationship(back_populates="categories")

class Operation(Base):
    __tablename__ = "operations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    type: Mapped[str] = mapped_column(String(16))
    amount: Mapped[float] = mapped_column(Float)
    category_id: Mapped[Optional[int]] = mapped_column(ForeignKey("categories.id"), nullable=True)
    account_id: Mapped[Optional[int]] = mapped_column(ForeignKey("accounts.id"), nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=datetime.datetime.utcnow)
    comment: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    user: Mapped["User"] = relationship(back_populates="operations")
    category: Mapped[Optional["Category"]] = relationship()
    account: Mapped[Optional["Account"]] = relationship()

class Envelope(Base):
    __tablename__ = "envelopes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id"))
    planned_amount: Mapped[float] = mapped_column(Float)
    spent_amount: Mapped[float] = mapped_column(Float, default=0.0)
    period_start: Mapped[datetime.datetime] = mapped_column(DateTime)
    period_end: Mapped[datetime.datetime] = mapped_column(DateTime)
    user: Mapped["User"] = relationship(back_populates="envelopes")
    category: Mapped["Category"] = relationship()

class Fund(Base):
    __tablename__ = "funds"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    name: Mapped[str] = mapped_column(String(255))
    target_amount: Mapped[float] = mapped_column(Float)
    current_amount: Mapped[float] = mapped_column(Float, default=0.0)
    monthly_contribution: Mapped[float] = mapped_column(Float, default=0.0)
    deadline: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    user: Mapped["User"] = relationship(back_populates="funds")

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

async def get_or_create_user(tg_id: int, name: str):
    async with async_session() as session:
        result = await session.execute(select(User).where(User.tg_id == tg_id))
        user = result.scalar_one_or_none()
        if not user:
            user = User(tg_id=tg_id, name=name)
            session.add(user)
            await session.commit()
            await session.refresh(user)
            await create_default_data(session, user)
        return user

async def create_default_data(session: AsyncSession, user: User):
    account = Account(user_id=user.id, name="Основной счёт", type="card", is_active=True)
    session.add(account)
    
    expense_categories = [
        ("🏠 Квартира", "expense", "🏠"),
        ("🛒 Продукты", "expense", "🛒"),
        ("🚗 Транспорт", "expense", "🚗"),
        ("👕 Одежда", "expense", "👕"),
        ("💊 Здоровье", "expense", "💊"),
        ("🎬 Развлечения", "expense", "🎬"),
        ("💳 Кредитки", "expense", "💳"),
        ("⚠️ Непредвиденные траты", "expense", "⚠️"),
        ("🏛️ Резерв", "expense", "🏛️"),
        ("📦 Подписки", "expense", "📦"),
        ("🎁 Подарки", "expense", "🎁"),
        ("📦 Прочее", "expense", "📦"),
    ]
    
    income_categories = [
        ("💰 Зарплата", "income", "💰"),
        ("💼 Подработка", "income", "💼"),
        ("🎁 Подарок", "income", "🎁"),
    ]
    
    for name, cat_type, emoji in expense_categories + income_categories:
        category = Category(user_id=user.id, name=name, type=cat_type, emoji=emoji, is_system=True)
        session.add(category)
    
    await session.commit()

async def add_operation(user_id: int, account_id: int, category_id: int, amount: float, op_type: str, description: str = ""):
    async with async_session() as session:
        operation = Operation(
            user_id=user_id,
            account_id=account_id,
            category_id=category_id,
            amount=amount,
            type=op_type,
            comment=description
        )
        session.add(operation)
        
        result = await session.execute(select(Account).where(Account.id == account_id))
        account = result.scalar_one()
        if op_type == "income":
            account.balance += amount
        else:
            account.balance -= amount
        
        await session.commit()
        await session.refresh(operation)
        return operation

async def get_user_default_account(user_id: int):
    async with async_session() as session:
        result = await session.execute(
            select(Account).where(Account.user_id == user_id, Account.is_active == True).limit(1)
        )
        return result.scalar_one()

async def find_category_by_name(user_id: int, description: str, op_type: str = "expense"):
    async with async_session() as session:
        result = await session.execute(
            select(Category).where(
                Category.user_id == user_id,
                Category.type == op_type,
                Category.is_active == True
            )
        )
        categories = result.scalars().all()
        
        description_lower = description.lower()
        for cat in categories:
            if cat.name.lower() in description_lower or description_lower in cat.name.lower():
                return cat
        
        return categories[0] if categories else None

async def get_today_summary(user_id: int):
    today_start = datetime.datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = today_start + datetime.timedelta(days=1)
    
    async with async_session() as session:
        result = await session.execute(
            select(Operation).where(
                Operation.user_id == user_id,
                Operation.created_at >= today_start,
                Operation.created_at < today_end
            ).order_by(Operation.created_at.desc())
        )
        ops = result.scalars().all()
        
        if not ops:
            return None
        
        income = sum(op.amount for op in ops if op.type == "income")
        expense = sum(op.amount for op in ops if op.type == "expense")
        
        for op in ops:
            await session.refresh(op, ["category"])
        
        return income, expense, ops

async def get_period_summary(user_id: int, start_date: datetime.datetime, end_date: datetime.datetime):
    async with async_session() as session:
        result = await session.execute(
            select(Operation).where(
                Operation.user_id == user_id,
                Operation.created_at >= start_date,
                Operation.created_at < end_date
            ).order_by(Operation.created_at.desc())
        )
        ops = result.scalars().all()
        
        if not ops:
            return None
        
        income = sum(op.amount for op in ops if op.type == "income")
        expense = sum(op.amount for op in ops if op.type == "expense")
        
        return income, expense, ops

async def get_all_users():
    async with async_session() as session:
        result = await session.execute(select(User))
        return result.scalars().all()

async def get_user_operations(user_id: int, limit: int = 20):
    async with async_session() as session:
        result = await session.execute(
            select(Operation).where(Operation.user_id == user_id)
            .order_by(Operation.created_at.desc()).limit(limit)
        )
        ops = result.scalars().all()
        for op in ops:
            await session.refresh(op, ["category"])
        return ops

async def delete_operation(user_id: int, op_id: int):
    async with async_session() as session:
        result = await session.execute(
            select(Operation).where(Operation.id == op_id, Operation.user_id == user_id)
        )
        operation = result.scalar_one_or_none()
        if operation:
            account_result = await session.execute(
                select(Account).where(Account.id == operation.account_id)
            )
            account = account_result.scalar_one_or_none()
            if account:
                if operation.type == "income":
                    account.balance -= operation.amount
                else:
                    account.balance += operation.amount
            await session.delete(operation)
            await session.commit()
            return True
        return False

async def get_user_categories(user_id: int, cat_type: Optional[str] = None):
    async with async_session() as session:
        query = select(Category).where(Category.user_id == user_id, Category.is_active == True)
        if cat_type:
            query = query.where(Category.type == cat_type)
        result = await session.execute(query)
        return result.scalars().all()

async def get_user_accounts(user_id: int):
    async with async_session() as session:
        result = await session.execute(
            select(Account).where(Account.user_id == user_id, Account.is_active == True)
        )
        return result.scalars().all()

async def get_user_by_tg_id(tg_id: int):
    async with async_session() as session:
        result = await session.execute(select(User).where(User.tg_id == tg_id))
        return result.scalar_one_or_none()

async def create_envelope(user_id: int, category_id: int, planned_amount: float, period_start: datetime.datetime, period_end: datetime.datetime):
    async with async_session() as session:
        envelope = Envelope(
            user_id=user_id,
            category_id=category_id,
            planned_amount=planned_amount,
            period_start=period_start,
            period_end=period_end
        )
        session.add(envelope)
        await session.commit()
        return envelope

async def get_user_envelopes(user_id: int):
    async with async_session() as session:
        result = await session.execute(
            select(Envelope).where(Envelope.user_id == user_id)
            .order_by(Envelope.period_start.desc())
        )
        envelopes = result.scalars().all()
        for env in envelopes:
            await session.refresh(env, ["category"])
        return envelopes

async def get_user_funds(user_id: int):
    async with async_session() as session:
        result = await session.execute(
            select(Fund).where(Fund.user_id == user_id, Fund.is_active == True)
        )
        return result.scalars().all()
