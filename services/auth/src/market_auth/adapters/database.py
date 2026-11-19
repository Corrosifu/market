"""Persistance du seul schéma auth, par le rôle auth_svc."""
from uuid import UUID

from market_auth.config import Settings
from market_auth.domain.identity import Principal, Role, User
from sqlalchemy import CheckConstraint, String, Text, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class UserRecord(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("role IN ('client', 'seller', 'ops')", name="users_role"),
        {"schema": "auth"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True)
    password_hash: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(String(16))


def create_engine(settings: Settings) -> AsyncEngine:
    return create_async_engine(settings.database_url(), pool_pre_ping=True, hide_parameters=True)


class PostgresUsers:
    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine
        self.sessions = async_sessionmaker(engine)

    async def by_email(self, email: str) -> User | None:
        async with self.sessions() as session:
            record = await session.scalar(select(UserRecord).where(UserRecord.email == email))
            if record is None:
                return None
            return User(Principal(record.id, Role(record.role)), record.email, record.password_hash)

    async def upsert(self, users: list[User]) -> None:
        query = insert(UserRecord).values([
            {"id": user.principal.id, "email": user.email,
             "password_hash": user.password_hash, "role": user.principal.role.value} for user in users
        ])
        query = query.on_conflict_do_update(
            index_elements=[UserRecord.email],
            set_={"id": query.excluded.id, "password_hash": query.excluded.password_hash, "role": query.excluded.role},
        )
        async with self.sessions.begin() as session:
            await session.execute(query)

    async def ready(self) -> bool:
        async with self.engine.connect() as connection:
            await connection.execute(text("SELECT 1 FROM auth.users LIMIT 1"))
        return True
