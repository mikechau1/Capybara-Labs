"""Database tables for the policies module.

- grants            card M2-02 (this file)
- access_requests   card M4-04

A grant is one row in which a department owner says "people matching this description may read
this slice of my department's data". Grants only add access; there are no deny rules. Revoking
sets `revoked_at` and keeps the row, so old audit events can still point to it.

The database enforces the shape of a grant, so a bad row cannot exist even if API code is wrong:
- the grantee is exactly one of: a department (or any) plus a minimum role, or one named user;
- a grant gives internal or restricted access (public needs no grant);
- a restricted grant must expire;
- user ids are never empty and never start or end with whitespace;
- a grant never changes after creation (triggers in migration 0003): the one allowed update is
  revoking it, once, and that covers every column, including ones added later. Rows are never
  deleted or truncated, so audit events can always point back to them.
- `created_at` and `revoked_at` are stamped with the database's clock, whatever the caller
  sends, so a grant can't be backdated, start in the future, or show a false revoke time.
  Restoring grants from a data-only backup therefore needs that trigger off, or every grant
  gets the restore time (and expired or revoked ones then fail their checks): restore as the
  owner with `ALTER TABLE grants DISABLE TRIGGER grants_stamp_created` around the load.

For the grants API (card M4-01): revoke with
`UPDATE grants SET revoked_at = now() WHERE id = :id AND revoked_at IS NULL` and treat 0 rows
as "already revoked" (409). Without the `revoked_at IS NULL` condition, the second of two
concurrent revokes hits the trigger's "already revoked" error instead.
"""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, enum_column
from app.shared.types import Role, Sensitivity, SourceType


class Grant(Base):
    __tablename__ = "grants"
    __table_args__ = (
        CheckConstraint(
            "(grantee_user_id IS NULL) <> (grantee_min_role IS NULL)", name="one_grantee_kind"
        ),
        CheckConstraint(
            "grantee_user_id IS NULL OR grantee_department IS NULL",
            name="user_grant_has_no_department",
        ),
        CheckConstraint("max_sensitivity <> 'public'", name="not_public"),
        CheckConstraint(
            "max_sensitivity <> 'restricted' OR expires_at IS NOT NULL",
            name="restricted_expires",
        ),
        CheckConstraint(
            "expires_at IS NULL OR expires_at > created_at", name="expires_after_created"
        ),
        CheckConstraint(
            "revoked_at IS NULL OR revoked_at >= created_at", name="revoked_after_created"
        ),
        CheckConstraint(
            "grantee_user_id IS NULL OR grantee_user_id"
            " ~ '^[^ \\t\\n\\r\\f\\v](.*[^ \\t\\n\\r\\f\\v])?$'",
            name="user_id_not_empty",
        ),
        CheckConstraint(
            "created_by ~ '^[^ \\t\\n\\r\\f\\v](.*[^ \\t\\n\\r\\f\\v])?$'",
            name="created_by_not_empty",
        ),
        # Scope resolution reads only active grants, looked up by grantee.
        Index(
            "ix_grants_active_grantee",
            "grantee_department",
            "grantee_user_id",
            postgresql_where=text("revoked_at IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()")
    )
    owning_department: Mapped[str] = mapped_column(ForeignKey("departments.id"), index=True)
    # Department grant: grantee_department (NULL = any department) + grantee_min_role.
    grantee_department: Mapped[str | None] = mapped_column(ForeignKey("departments.id"))
    grantee_min_role: Mapped[Role | None] = mapped_column(enum_column(Role, "grantee_min_role"))
    # Named-user grant: the Keycloak user ID (used by approved access requests, card M4-04).
    grantee_user_id: Mapped[str | None] = mapped_column(String(255))
    source_type: Mapped[SourceType | None] = mapped_column(  # NULL = every source type
        enum_column(SourceType, "source_type")
    )
    # Covers this level and every level below it.
    max_sensitivity: Mapped[Sensitivity] = mapped_column(
        enum_column(Sensitivity, "max_sensitivity")
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[str] = mapped_column(String(255))  # user ID of the owner who created it
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
