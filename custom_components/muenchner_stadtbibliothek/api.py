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
    BUTTON_ADVANCED_SEARCH,
    BUTTON_LOGIN,
    BUTTON_LOGIN_NAME,
    BUTTON_RENEW_MARKED,
    BUTTON_SEARCH,
    BUTTON_TO_OVERVIEW,
    DEFAULT_BASE_URL,
    LINK_ACCOUNT,
    LINK_LOGOUT,
    MAX_LOOKUPS_PER_UPDATE,
    REQUEST_TIMEOUT,
    SEARCH_FIELD_SIGNATURE,
    SEARCH_FIELD_TITLE,
    SEARCH_OPERATOR_AND,
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
    parse_isbn,
    parse_loans,
    parse_login_form,
    parse_page,
    parse_search_form,
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
    # catalog searches done in this update: barcode -> ISBN, or None when no unique record was found
    looked_up: dict[str, str | None] = field(default_factory=dict)


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
                    raise LibraryConnectionError(f"HTTP {resp.status} {resp.reason or ''} ({resp.url.host}{resp.url.path})".replace("  ", " "))
                return await resp.text(), str(resp.url)
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            raise LibraryConnectionError(f"{type(err).__name__}: {err}".rstrip(": ")) from err

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
            button = login_submit_button(html, BUTTON_LOGIN_NAME, BUTTON_LOGIN)
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

    async def _lookup_isbns(self, page: AdisPage, loans: list[Loan]) -> tuple[AdisPage, dict[str, str | None]]:
        """Search the catalog once per item like a user would (title + shelf mark + library).

        Only a unique hit opens the full record directly; its ISBN is taken. Anything else
        (no hit, a result list, a changed page) gives None. Errors stop the lookups but never
        the update. Returns the last page (for the logout) and the results.
        """
        results: dict[str, str | None] = {}
        try:
            if BUTTON_ADVANCED_SEARCH not in page.buttons and BUTTON_TO_OVERVIEW in page.buttons:
                page, _ = await self._click_button(page, BUTTON_TO_OVERVIEW)
            for loan in loans[:MAX_LOOKUPS_PER_UPDATE]:
                if BUTTON_ADVANCED_SEARCH not in page.buttons:
                    break
                page, _ = await self._click_button(page, BUTTON_ADVANCED_SEARCH)
                form = parse_search_form(page, (SEARCH_FIELD_TITLE, SEARCH_FIELD_SIGNATURE), SEARCH_OPERATOR_AND, BUTTON_SEARCH)
                if form is None or not page.action:
                    _LOGGER.debug("Advanced search form not recognized")
                    break
                values = dict(form.fields)
                values.update(page.hidden)
                values.update(scriptEnabled="true", scrollPos="0", keyCode="0", source="$B", selected="", focus=form.submit[2] or "")
                values[form.library] = loan.library
                (field1, input1), (field2, input2) = form.rows[0], form.rows[1]
                values.update({field1: SEARCH_FIELD_TITLE, input1: loan.title, form.operators[0]: SEARCH_OPERATOR_AND})
                if loan.signature:
                    values.update({field2: SEARCH_FIELD_SIGNATURE, input2: loan.signature})
                name, label, _ = form.submit
                data = [*values.items(), (name, label), (name, "pressed")]
                page, _ = await self._load("POST", page.action, data)
                results[loan.barcode] = parse_isbn(page)
                _LOGGER.debug("Cover lookup for %s: %s", loan.barcode, results[loan.barcode] or "no unique record")
        except LibraryError as err:
            _LOGGER.debug("Cover lookup stopped: %s", err)
        return page, results

    async def async_fetch(self, known_isbns: dict[str, str | None] | None = None) -> AccountData:
        """Card validity and current loans.

        known_isbns: results of earlier lookups (barcode -> ISBN or None). None disables lookups;
        otherwise items not in it are searched in the catalog once.
        """
        async with self._lock:
            overview = await self._login()
            last = overview
            try:
                valid = parse_card_valid_until(overview)
                loans_page = await self._open_loans(overview)
                loans = parse_loans(loans_page) if loans_page else []
                if loans_page is not None:
                    last = loans_page
                looked_up: dict[str, str | None] = {}
                if known_isbns is not None:
                    new = [loan for loan in loans if loan.barcode not in known_isbns]
                    if new:
                        last, looked_up = await self._lookup_isbns(last, new)
                    for loan in loans:
                        loan.isbn = looked_up.get(loan.barcode) or known_isbns.get(loan.barcode)
                return AccountData(valid, loans, looked_up=looked_up)
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
