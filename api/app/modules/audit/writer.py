"""Audit write helper. Card M3-07 owns this file."""

from app.modules.audit.schemas import AuditEvent


def record(event: AuditEvent) -> None:
    # TODO(M3-07): insert in the caller's transaction; if the insert fails, the request fails.
    raise NotImplementedError("Card M3-07")
