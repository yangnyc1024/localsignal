from abc import ABC, abstractmethod

from localsignal_engine.models import Mention, Place


class IngestionAdapter(ABC):
    source: str

    @abstractmethod
    def fetch_mentions(self, places: list[Place]) -> list[Mention]:
        """Return normalized mentions for known places."""
