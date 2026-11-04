from collections.abc import Generator

from fastapi import Request

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool


class Base(DeclarativeBase):
    pass


def make_session_factory(database_url: str):
    options = {"connect_args": {"check_same_thread": False}} if database_url.startswith("sqlite") else {}
    if database_url in {"sqlite://", "sqlite:///:memory:"}:
        options["poolclass"] = StaticPool
    engine = create_engine(database_url, pool_pre_ping=True, **options)
    return engine, sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db(request: Request) -> Generator[Session, None, None]:
    factory = getattr(request.app.state, "session_factory", None)
    if factory is None:
        raise RuntimeError("Database is not initialized")
    with factory() as session:
        yield session
