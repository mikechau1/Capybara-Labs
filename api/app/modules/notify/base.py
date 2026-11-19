from typing import Protocol


class Notifier(Protocol):
    def notify_department_owners(self, department: str, message: str) -> None: ...
