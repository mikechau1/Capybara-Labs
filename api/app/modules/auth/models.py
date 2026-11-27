"""Tables for the auth module. Card M2-01 owns this file.

Identity (department, role, admin flag) lives in Keycloak and arrives in the token on every
request; it is never stored here, so it cannot go stale. This table only remembers display
names, so audit pages and request lists can show a name for a user ID.
"""

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, Timestamps


class UserProfile(Timestamps, Base):
    __tablename__ = "user_profiles"

    user_id: Mapped[str] = mapped_column(String(255), primary_key=True)  # Keycloak subject ID
    display_name: Mapped[str] = mapped_column(String(200))
