"""Enable the pgvector extension, used by the chunks table (card M2-01) for embeddings.

Revision ID: 0001
Revises:
Created: 2026-11-19
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Needs a role allowed to create extensions. The local Docker user is a superuser;
    # a managed database (card M5-02) may need the extension enabled by an administrator.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")


def downgrade() -> None:
    op.execute("DROP EXTENSION IF EXISTS vector")
