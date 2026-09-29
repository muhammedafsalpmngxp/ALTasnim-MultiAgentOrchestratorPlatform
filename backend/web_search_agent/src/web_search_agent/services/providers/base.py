from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class SearchQuery:
    text: str
    max_results: int
    freshness: str | None = None  # day | week | month | year
    include_domains: list[str] = field(default_factory=list)
    exclude_domains: list[str] = field(default_factory=list)

    def text_with_site_filters(self) -> str:
        """Query text with `site:` operators, for engines without native domain filters."""
        if not self.include_domains:
            return self.text
        return f"{self.text} ({' OR '.join(f'site:{domain}' for domain in self.include_domains)})"


@dataclass
class SearchHit:
    url: str
    title: str
    snippet: str = ""
    published_date: str | None = None
    provider: str = ""


class SearchProvider(ABC):
    name: str

    @property
    def is_configured(self) -> bool:
        return True

    @abstractmethod
    async def search(self, query: SearchQuery) -> list[SearchHit]:
        """Return hits for the query. Raise on transport/API errors so the next provider is tried."""
