"""Client for the account pages of the Münchner Stadtbibliothek (no Home Assistant imports).

Every call runs a complete, short session: catalog start page, "Mein Konto",
login (OpenID Connect form), overview, loans, optionally renewal, logout.
That is about 6 page loads per update; the session is closed again right away.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import date, datetime

import aiohttp

from .const import (
    BUTTON_LOGIN,
    BUTTON_RENEW_MARKED,
    DEFAULT_BASE_URL,
    LINK_ACCOUNT,
    LINK_LOGOUT,
    REQUEST_TIMEOUT,
    START_PATH,
    USER_AGENT,
)
from .parser import (
    LINK_PREFIX,
    AdisPage,
    Loan,
    find_link,
    is_login_page,
    loans_link,
    login_error,
    login_submit_button,
    page_message,
    parse_card_valid_until,
    parse_loans,
    parse_login_form,
    parse_page,
    renewed_today,
)

_LOGGER = logging.getLogger(__name__)


class LibraryError(Exception):
    """Base error."""


class LibraryConnectionError(LibraryError):
    """Catalog not reachable."""


class LibraryAuthError(LibraryError):
    """Card number or password rejected."""


class LibraryParseError(LibraryError):
    """A page did not look as expected (catalog changed?)."""


class LibraryRenewError(LibraryError):
    """Renewal not possible or not confirmed."""

    def __init__(self, message: str, account: "AccountData | None" = None) -> None:
        super().__init__(message)
        self.account = account  # loans as shown after the attempt, if the catalog answered


@dataclass
class AccountData:
    """Everything one update returns."""

    card_valid_until: date | None
    loans: list[Loan] = field(default_factory=list)
    updated: datetime = field(default_factory=datetime.now)


@dataclass
class RenewResult:
    """Outcome of one renewal."""

    account: AccountData
    loan: Loan | None
    message: str | None


class LibraryClient:
    """Talks to the aDIS catalog."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        card_number: str,
        password: str,
        base_url: str = DEFAULT_BASE_URL,
    ) -> None:
        self._session = session
        self._card_number = card_number.strip()
        self._password = password
        self._base_url = base_url.rstrip("/")
        self._lock = asyncio.Lock()

    # ---- HTTP -------------------------------------------------------------

    async def _request(self, method: str, url: str, data: list[tuple[str, str]] | None = None) -> tuple[str, str]:
        try:
            async with self._session.request(
                method,
                url,
                data=data,
                headers={"User-Agent": USER_AGENT, "Accept-Language": "de-DE,de;q=0.9"},
                timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
                allow_redirects=True,
            ) as resp:
                if resp.status >= 400:
                    raise LibraryConnectionError(f"HTTP {resp.status} for {resp.url.path}")
                return await resp.text(), str(resp.url)
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            raise LibraryConnectionError(str(err) or type(err).__name__) from err

    async def _load(self, method: str, url: str, data: list[tuple[str, str]] | None = None) -> tuple[AdisPage, str]:
        html, final_url = await self._request(method, url, data)
        return parse_page(html, final_url), html

    def _form(self, page: AdisPage, **overrides: str) -> list[tuple[str, str]]:
        values = dict(page.hidden)
        values.update(scriptEnabled="true", scrollPos="0")
        values.update(overrides)
        return list(values.items())

    async def _click_link(self, page: AdisPage, code: str) -> tuple[AdisPage, str]:
        if not page.action:
            raise LibraryParseError("page without form")
        data = self._form(page, keyCode="0", selected=LINK_PREFIX + code, overrideScrollPos="0")
        return await self._load("POST", page.action, data)

    async def _click_button(
        self, page: AdisPage, label: str, extra: list[tuple[str, str]] | None = None
    ) -> tuple[AdisPage, str]:
        if not page.action or label not in page.buttons:
            raise LibraryParseError(f"button '{label}' not found")
        name, data_fld = page.buttons[label]
        data = self._form(page, keyCode="0", focus=data_fld or "", source="$B", selected="")
        data += [(name, label), *(extra or []), (name, "pressed"), ("overrideScrollPos", "0")]
        return await self._load("POST", page.action, data)

    # ---- session ----------------------------------------------------------

    async def _login(self) -> AdisPage:
        """Log in and return the account overview."""
        self._session.cookie_jar.clear()
        start, _ = await self._load("GET", self._base_url + START_PATH)
        code = find_link(start, LINK_ACCOUNT)
        if code is None:
            raise LibraryParseError(f"link '{LINK_ACCOUNT}' not found on the start page")
        page, html = await self._click_link(start, code)

        if is_login_page(html):
            form = parse_login_form(html, page.url)
            button = login_submit_button(html, BUTTON_LOGIN)
            if form is None or button is None:
                raise LibraryParseError("login form not recognized")
            action, fields, user_field, password_field = form
            data = [*fields.items(), (user_field, self._card_number), (password_field, self._password), button]
            page, html = await self._load("POST", action, data)
            if is_login_page(html):
                raise LibraryAuthError(login_error(html) or "login rejected")

        if parse_card_valid_until(page) is None and loans_link(page)[0] is None:
            raise LibraryParseError("account overview not recognized after login")
        return page

    async def _logout(self, page: AdisPage) -> None:
        """End the catalog session (best effort)."""
        code = find_link(page, LINK_LOGOUT)
        if code is None:
            return
        try:
            await self._click_link(page, code)
        except LibraryError as err:
            _LOGGER.debug("Logout failed: %s", err)

    async def _open_loans(self, overview: AdisPage) -> AdisPage | None:
        code, count = loans_link(overview)
        if code is None:
            return None
        page, _ = await self._click_link(overview, code)
        if count and not parse_loans(page):
            raise LibraryParseError("loans table not recognized")
        return page

    # ---- public -----------------------------------------------------------

    async def async_fetch(self) -> AccountData:
        """Card validity and current loans."""
        async with self._lock:
            overview = await self._login()
            last = overview
            try:
                valid = parse_card_valid_until(overview)
                loans_page = await self._open_loans(overview)
                if loans_page is not None:
                    last = loans_page
                return AccountData(valid, parse_loans(loans_page) if loans_page else [])
            finally:
                await self._logout(last)

    async def async_renew(self, barcode: str) -> RenewResult:
        """Renew one loan identified by its barcode."""
        async with self._lock:
            overview = await self._login()
            last = overview
            try:
                valid = parse_card_valid_until(overview)
                loans_page = await self._open_loans(overview)
                if loans_page is None:
                    raise LibraryRenewError("no current loans")
                last = loans_page
                loans = parse_loans(loans_page)
                before = next((loan for loan in loans if loan.barcode == barcode), None)
                if before is None:
                    raise LibraryRenewError(f"loan {barcode} not found")
                if not before.renewable:
                    raise LibraryRenewError(before.hint or "not renewable")
                if not before.checkbox:
                    raise LibraryParseError("checkbox of the loan not found")

                result_page, _ = await self._click_button(
                    loans_page, BUTTON_RENEW_MARKED, [("$RTable_checkbox[]", before.checkbox)]
                )
                last = result_page
                after_loans = parse_loans(result_page)
                if not after_loans:
                    raise LibraryParseError("loans table not recognized after renewal")
                after = next((loan for loan in after_loans if loan.barcode == barcode), None)
                account = AccountData(valid, after_loans)
                renewed = after is not None and (
                    renewed_today(after)
                    or (after.due_date and before.due_date and after.due_date > before.due_date)
                )
                if not renewed:
                    raise LibraryRenewError(after.hint if after else "loan missing after renewal", account)
                return RenewResult(account, after, page_message(result_page))
            finally:
                await self._logout(last)
