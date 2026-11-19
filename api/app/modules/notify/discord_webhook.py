"""Discord channel webhook notifier. Card M4-06 owns this file."""


class DiscordWebhookNotifier:
    def __init__(self, webhook_urls: dict[str, str]) -> None:
        self.webhook_urls = webhook_urls  # department -> webhook address

    def notify_department_owners(self, department: str, message: str) -> None:
        raise NotImplementedError("Card M4-06")
