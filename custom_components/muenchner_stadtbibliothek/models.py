"""Data of one library account (no Home Assistant imports).

Where the fields come from:
- Loan: the loans table of the catalog (parser.parse_loans); isbn and cover_url are added
  by the coordinator from the stored cover lookups.
- AccountData: one catalog session (api.LibraryClient.async_fetch / async_renew).
- Lookup: one catalog search for a new item (title + shelf mark + library).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime

from .const import HINT_RENEWED_TODAY


@dataclass
class Loan:
    """One borrowed item, as the loans table shows it."""

    barcode: str  # "Mediennummer", identifies the item
    title: str
    author: str | None  # statement of responsibility from the title line (after " / "), not always a person
    full_title: str  # title line as shown in the catalog
    shelf_mark: str | None  # "Signatur"
    library: str
    due_date: date | None
    hint: str  # column "Hinweis", e.g. "verlängerbar - Stand 02.03.2030"
    renewable: bool
    checkbox: str | None = None  # value of the row checkbox, only valid for the page it came from
    isbn: str | None = None  # ISBN-13/EAN from the catalog record, looked up once per item
    cover_url: str | None = None  # cover stored in Home Assistant (local URL)

    @property
    def renewed_today(self) -> bool:
        """True if the catalog reports the item as renewed today."""
        return self.hint.startswith(HINT_RENEWED_TODAY)

    def as_dict(self) -> dict:
        """Attributes for Home Assistant (dates as ISO strings, no page specific data)."""
        data = asdict(self)
        data.pop("checkbox")
        data["due_date"] = self.due_date.isoformat() if self.due_date else None
        data["renewed_today"] = self.renewed_today
        return data


@dataclass
class Lookup:
    """Result of one catalog search; isbn None when no unique record was found."""

    isbn: str | None
    cover: bytes | None = None
    content_type: str | None = None


@dataclass
class AccountData:
    """Everything one catalog session returns."""

    card_valid_until: date | None
    loans: list[Loan] = field(default_factory=list)
    fetched_at: datetime = field(default_factory=datetime.now)
    looked_up: dict[str, Lookup] = field(default_factory=dict)  # barcode -> search done in this session


@dataclass
class RenewResult:
    """Outcome of one renewal."""

    account: AccountData
    loan: Loan | None
    message: str | None
