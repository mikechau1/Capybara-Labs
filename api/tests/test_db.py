"""The database layer from card M1-04: migrations, the `db` fixture, and the session dependency."""

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, select, text
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from app.db import DbSession
from tests.conftest import API_ROOT


class _TestBase(DeclarativeBase):
    """Separate from app.db.Base so these test-only tables never reach a migration."""


class Note(_TestBase):
    __tablename__ = "test_notes"
    id: Mapped[int] = mapped_column(primary_key=True)
    body: Mapped[str]


def _create_notes_table(db: Session) -> None:
    # Created inside the test's transaction, so it disappears with the rollback.
    _TestBase.metadata.create_all(db.connection())


def test_migrations_ran_to_head(db: Session):
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(API_ROOT / "migrations"))
    head = ScriptDirectory.from_config(config).get_current_head()

    assert db.scalar(text("SELECT version_num FROM alembic_version")) == head
    assert db.scalar(text("SELECT count(*) FROM pg_extension WHERE extname = 'vector'")) == 1


def test_write_and_read_back(db: Session):
    _create_notes_table(db)
    db.add(Note(body="hello"))
    db.commit()

    assert db.scalars(select(Note.body)).all() == ["hello"]


def test_writes_never_reach_the_real_database(db: Session, db_engine: Engine):
    _create_notes_table(db)
    db.add(Note(body="should vanish"))
    db.commit()  # a savepoint, not a real commit

    # A separate connection sees the database as committed: no table, so nothing leaked.
    with db_engine.connect() as other:
        assert other.scalar(text("SELECT to_regclass('test_notes')")) is None


def test_pgvector_works(db: Session):
    # Euclidean distance between two 3-d vectors, the kind of query retrieval (M2-07) runs.
    distance = db.scalar(text("SELECT '[1,2,3]'::vector <-> '[1,2,4]'::vector"))
    assert distance == 1.0


def test_endpoints_get_the_test_session(db_client):
    @db_client.app.get("/test/which-database")
    def which_database(session: DbSession) -> dict[str, str]:
        return {"database": session.scalar(text("SELECT current_database()"))}

    assert db_client.get("/test/which-database").json() == {"database": "capybara_test"}
