"""HTML parsing for the aDIS catalog pages (no Home Assistant imports).

aDIS is a stateful web application: every page has one form ("Form0") with hidden
fields (identity, requestCount, ...). Links are JavaScript handlers that submit this
form with selected="ZTEXT       <code>"; buttons submit it with their own name.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import date
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from .const import (
    COLUMN_DUE,
    COLUMN_HINT,
    COLUMN_LIBRARY,
    COLUMN_TITLE,
    HINT_RENEWABLE,
    HINT_RENEWED_TODAY,
    LINK_LOANS_PATTERN,
    TERM_CARD_VALID,
)

# Prefix aDIS puts in front of a link code (htmlOnLink in aDISMain.js)
LINK_PREFIX = "ZTEXT       "

_FN_RE = re.compile(r"function\s+(fn\d+)\s*\(e\)\s*\{[^}]*?htmlOnLink\(\s*[\"']([^\"']+)[\"']\s*\)")
_BIND_RE = re.compile(r"getElementById\(\s*[\"'](idfn\d+)[\"']\s*\)\??\.addEventListener\(\s*[\"']click[\"']\s*,\s*(fn\d+)")
_RENEWALS_RE = re.compile(r"(\d+)\s+Verlängerung")
_DATE_RE = re.compile(r"(\d{1,2})\.(\d{1,2})\.(\d{4})")


@dataclass
class Loan:
    """One borrowed item."""

    barcode: str
    title: str
    author: str | None
    full_title: str
    signature: str | None
    library: str
    due_date: date | None
    hint: str
    renewable: bool
    renewals: int | None
    checkbox: str | None = None  # value of the row checkbox, only valid for the page it came from

    def as_dict(self) -> dict:
        """Attributes for Home Assistant (dates as ISO strings, no page specific data)."""
        data = asdict(self)
        data.pop("checkbox")
        data["due_date"] = self.due_date.isoformat() if self.due_date else None
        return data


@dataclass
class AdisPage:
    """The parts of an aDIS page the client needs to continue."""

    url: str
    action: str | None
    hidden: dict[str, str] = field(default_factory=dict)
    links: dict[str, str] = field(default_factory=dict)  # link text -> link code
    buttons: dict[str, tuple[str, str | None]] = field(default_factory=dict)  # value -> (name, data-fld)
    soup: BeautifulSoup | None = None


def _text(tag: Tag | None) -> str:
    return " ".join(tag.get_text(" ", strip=True).split()) if tag else ""


def _lines(tag: Tag) -> list[str]:
    """Text of a cell split at <br> (and other line breaks)."""
    return [" ".join(part.split()) for part in tag.get_text("\n").split("\n") if part.strip()]


def parse_date(value: str) -> date | None:
    """Parse a German date (dd.mm.yyyy) anywhere in the text."""
    match = _DATE_RE.search(value or "")
    if not match:
        return None
    day, month, year = (int(x) for x in match.groups())
    try:
        return date(year, month, day)
    except ValueError:
        return None


def parse_page(html: str, url: str) -> AdisPage:
    """Read form, hidden fields, link codes and buttons of an aDIS page."""
    soup = BeautifulSoup(html, "html.parser")
    form = soup.find("form", attrs={"name": "Form0"}) or soup.find("form")
    page = AdisPage(url=url, action=None, soup=soup)
    if form is None:
        return page
    page.action = urljoin(url, form.get("action") or url)
    for inp in form.find_all("input", attrs={"type": "hidden"}):
        if inp.get("name"):
            page.hidden[inp["name"]] = inp.get("value", "")
    for inp in form.find_all("input", attrs={"type": "submit"}):
        if inp.get("name") and inp.get("value"):
            # the same button can appear twice (above and below a table); keep the first
            page.buttons.setdefault(inp["value"].strip(), (inp["name"], inp.get("data-fld")))

    scripts = "\n".join(s.get_text() for s in soup.find_all("script") if not s.get("src"))
    codes = dict(_FN_RE.findall(scripts))  # fn name -> code
    bound = {link_id: codes.get(fn) for link_id, fn in _BIND_RE.findall(scripts)}
    for anchor in soup.find_all("a", id=re.compile(r"^idfn\d+$")):
        # handlers are named after the link id (idfn22 -> fn22); the binding is the fallback
        code = codes.get(anchor["id"][2:]) or bound.get(anchor["id"])
        text = _text(anchor)
        if code and text:
            page.links.setdefault(text, code)
    return page


def find_link(page: AdisPage, text: str | None = None, pattern: str | None = None) -> str | None:
    """Code of a link by exact text or regular expression."""
    if text is not None:
        return page.links.get(text)
    regex = re.compile(pattern or "")
    return next((code for label, code in page.links.items() if regex.search(label)), None)


def loans_link(page: AdisPage) -> tuple[str | None, int]:
    """Code of the "N Ausleihen" link and the number in it (no link means no loans)."""
    regex = re.compile(LINK_LOANS_PATTERN)
    for label, code in page.links.items():
        match = regex.match(label)
        if match:
            return code, int(match.group(1))
    return None, 0


def is_login_page(html: str) -> bool:
    """True if the page contains a password field (login form)."""
    soup = BeautifulSoup(html, "html.parser")
    return soup.find("input", attrs={"type": "password"}) is not None


def parse_login_form(html: str, url: str) -> tuple[str, dict[str, str], str, str] | None:
    """Action, base fields, user field and password field of the login form."""
    soup = BeautifulSoup(html, "html.parser")
    password = soup.find("input", attrs={"type": "password"})
    if password is None:
        return None
    form = password.find_parent("form")
    if form is None:
        return None
    fields: dict[str, str] = {}
    user_field = None
    for inp in form.find_all("input"):
        name, kind = inp.get("name"), (inp.get("type") or "text").lower()
        if not name:
            continue
        if kind == "hidden":
            fields[name] = inp.get("value", "")
        elif kind in ("text", "tel", "number", "email") and user_field is None:
            user_field = name
    if user_field is None:
        return None
    return urljoin(url, form.get("action") or url), fields, user_field, password["name"]


def login_submit_button(html: str, name: str, label: str) -> tuple[str, str] | None:
    """Name and value of the login button, by field name first (the label depends on the language)."""
    soup = BeautifulSoup(html, "html.parser")
    buttons = [b for b in soup.find_all("input", attrs={"type": "submit"}) if b.get("name")]
    for button in buttons:
        if button["name"] == name:
            return button["name"], button.get("value", "")
    for button in buttons:
        if (button.get("value") or "").strip() == label:
            return button["name"], button["value"]
    return None


def login_error(html: str) -> str | None:
    """Error message shown on the login page, if any."""
    soup = BeautifulSoup(html, "html.parser")
    for selector in (".error", ".alert", ".fehler", "[role=alert]", ".message"):
        tag = soup.select_one(selector)
        if tag and _text(tag):
            return _text(tag)
    return None


def parse_card_valid_until(page: AdisPage) -> date | None:
    """Date after "Ausweis gültig bis" on the account overview."""
    if page.soup is None:
        return None
    for term in page.soup.find_all("dt"):
        if _text(term).startswith(TERM_CARD_VALID):
            return parse_date(_text(term.find_next_sibling("dd")))
    return None


def page_message(page: AdisPage) -> str | None:
    """General message above the loans table (e.g. after a renewal)."""
    if page.soup is None:
        return None
    for tag in page.soup.find_all(string=re.compile("verlängern", re.I)):
        text = " ".join(str(tag).split())
        if text.startswith("Sie haben"):
            return text
    return None


def _split_title(full: str) -> tuple[str, str | None]:
    if " / " in full:
        title, author = full.split(" / ", 1)
        return title.strip(), author.split(" ; ")[0].strip() or None
    return full.strip(), None


def parse_loans(page: AdisPage) -> list[Loan]:
    """Rows of the loans table, columns found by their header text."""
    if page.soup is None:
        return []
    for table in page.soup.find_all("table"):
        headers = [_text(th) for th in table.find_all("th")]
        if COLUMN_DUE in headers and COLUMN_TITLE in headers:
            break
    else:
        return []

    index = {name: headers.index(name) for name in (COLUMN_DUE, COLUMN_LIBRARY, COLUMN_TITLE, COLUMN_HINT) if name in headers}
    body = table.find("tbody") or table
    loans: list[Loan] = []
    for row in body.find_all("tr"):
        cells = row.find_all("td")
        if len(cells) < len(headers):
            continue
        title_lines = _lines(cells[index[COLUMN_TITLE]])
        if not title_lines:
            continue
        full_title = title_lines[0]
        barcode = next((line for line in reversed(title_lines[1:]) if re.fullmatch(r"\d{6,}", line)), None)
        signature = next((line for line in title_lines[1:] if line != barcode), None)
        hint_lines = _lines(cells[index[COLUMN_HINT]]) if COLUMN_HINT in index else []
        hint = ", ".join(hint_lines)
        renewals = _RENEWALS_RE.search(hint)
        checkbox = row.find("input", attrs={"type": "checkbox"})
        title, author = _split_title(full_title)
        loans.append(
            Loan(
                barcode=barcode or full_title,
                title=title,
                author=author,
                full_title=full_title,
                signature=signature,
                library=_text(cells[index[COLUMN_LIBRARY]]) if COLUMN_LIBRARY in index else "",
                due_date=parse_date(_text(cells[index[COLUMN_DUE]])),
                hint=hint,
                renewable=bool(hint_lines) and hint_lines[0].lower().startswith(HINT_RENEWABLE),
                renewals=int(renewals.group(1)) if renewals else None,
                checkbox=checkbox.get("value") if checkbox else None,
            )
        )
    return loans


def renewed_today(loan: Loan) -> bool:
    """True if the catalog reports the loan as renewed today."""
    return loan.hint.startswith(HINT_RENEWED_TODAY)
