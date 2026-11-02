"""Client for the account pages of the Münchner Stadtbibliothek (no Home Assistant imports).

Every call runs a complete, short session: catalog start page, "Mein Konto",
login (OpenID Connect form), overview, loans, optionally renewal, logout.
That is about 6 page loads per update; the session is closed again right away.
"""

from __future__ import annotations

import asyncio
import logging
from urllib.parse import urlsplit, urlunsplit

import aiohttp

from .const import (
    BUTTON_ADVANCED_SEARCH,
    BUTTON_LOGIN,
    BUTTON_LOGIN_NAME,
    BUTTON_RENEW_MARKED,
    BUTTON_SEARCH,
    BUTTON_TO_OVERVIEW,
    COVER_URL,
    DEFAULT_BASE_URL,
    LINK_ACCOUNT,
    LINK_LOGOUT,
    MAX_COVER_BYTES,
    MAX_LOOKUPS_PER_UPDATE,
    REQUEST_TIMEOUT,
    SEARCH_FIELD_SHELF_MARK,
    SEARCH_FIELD_TITLE,
    SEARCH_OPERATOR_AND,
    START_PATH,
    USER_AGENT,
)
from .models import AccountData, Loan, Lookup, RenewResult
from .parser import (
    LINK_PREFIX,
    AdisPage,
    SearchForm,
    find_link,
    is_login_page,
    loans_link,
    login_error,
    login_submit_button,
    page_message,
    parse_card_valid_until,
    parse_cover_src,
    parse_isbn,
    parse_loans,
    parse_login_form,
    parse_page,
    parse_search_form,
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

    def __init__(self, message: str, account: AccountData | None = None) -> None:
        super().__init__(message)
        self.account = account  # loans as shown after the attempt, if the catalog answered


def browser_url(url: str) -> str:
    """URL as a browser sends it: without the default port (the catalog redirects to ":443",
    and the cover service rejects a referer with it)."""
    parts = urlsplit(url)
    if (parts.scheme, parts.port) in (("https", 443), ("http", 80)):
        parts = parts._replace(netloc=parts.hostname or "")
    return urlunsplit(parts)


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

    async def async_close(self) -> None:
        """Close the HTTP session of this client (after unload or a login check)."""
        await self._session.close()

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

    async def _fetch_image(self, url: str, referer: str) -> tuple[bytes, str] | None:
        """Load an image the way the browser does when it shows the page `referer`.

        None means there is no cover (a clear answer, not searched again). Temporary problems
        (timeout, connection error, server error) raise LibraryConnectionError: the item is then
        searched again at the next update.
        """
        url, referer = browser_url(url), browser_url(referer)
        try:
            async with self._session.request(
                "GET",
                url,
                headers={
                    "User-Agent": USER_AGENT,
                    "Accept": "image/avif,image/webp,image/png,image/jpeg,image/*;q=0.8",
                    "Referer": referer,
                },
                timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
                allow_redirects=True,
            ) as resp:
                if resp.status >= 500:
                    raise LibraryConnectionError(f"cover: HTTP {resp.status}")
                content_type = (resp.content_type or "").lower()
                if resp.status != 200 or not content_type.startswith("image/"):
                    _LOGGER.debug("No cover at %s: HTTP %s %s", url, resp.status, content_type)
                    return None
                body = await resp.read()
                if not body or len(body) > MAX_COVER_BYTES:
                    return None
                return body, content_type
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            raise LibraryConnectionError(f"cover: {type(err).__name__}: {err}".rstrip(": ")) from err

    async def _load(self, method: str, url: str, data: list[tuple[str, str]] | None = None) -> AdisPage:
        html, final_url = await self._request(method, url, data)
        return parse_page(html, final_url)

    async def _click_link(self, page: AdisPage, code: str) -> AdisPage:
        """Follow an aDIS link: post the page's form with the link code."""
        if not page.action:
            raise LibraryParseError("page without form")
        values = {**page.hidden, "scriptEnabled": "true", "scrollPos": "0", "keyCode": "0", "selected": LINK_PREFIX + code, "overrideScrollPos": "0"}
        return await self._load("POST", page.action, list(values.items()))

    async def _press(
        self,
        page: AdisPage,
        button: tuple[str, str, str | None],
        fields: dict[str, str] | None = None,
        extra: list[tuple[str, str]] | None = None,
    ) -> AdisPage:
        """Submit the page's form with a button, like the browser does.

        button: (name, value, data-fld). fields: visible form fields to send (e.g. a search form),
        extra: additional pairs such as checked checkboxes. The browser sends the button twice:
        once with its value and once as "pressed".
        """
        if not page.action:
            raise LibraryParseError("page without form")
        name, label, data_fld = button
        values = {**(fields or {}), **page.hidden}
        values.update(scriptEnabled="true", scrollPos="0", keyCode="0", focus=data_fld or "", source="$B", selected="")
        data = [*values.items(), (name, label), *(extra or []), (name, "pressed"), ("overrideScrollPos", "0")]
        return await self._load("POST", page.action, data)

    async def _click_button(self, page: AdisPage, label: str, extra: list[tuple[str, str]] | None = None) -> AdisPage:
        """Press a button found by its label."""
        if label not in page.buttons:
            raise LibraryParseError(f"button '{label}' not found")
        name, data_fld = page.buttons[label]
        return await self._press(page, (name, label, data_fld), extra=extra)

    # ---- session ----------------------------------------------------------

    async def _login(self) -> AdisPage:
        """Log in and return the account overview."""
        self._session.cookie_jar.clear()
        start = await self._load("GET", self._base_url + START_PATH)
        code = find_link(start, LINK_ACCOUNT)
        if code is None:
            raise LibraryParseError(f"link '{LINK_ACCOUNT}' not found on the start page")
        page = await self._click_link(start, code)

        if is_login_page(page):
            form = parse_login_form(page)
            button = login_submit_button(page, BUTTON_LOGIN_NAME, BUTTON_LOGIN)
            if form is None or button is None:
                raise LibraryParseError("login form not recognized")
            action, hidden, user_field, password_field = form
            data = [*hidden.items(), (user_field, self._card_number), (password_field, self._password), button]
            page = await self._load("POST", action, data)
            if is_login_page(page):
                raise LibraryAuthError(login_error(page) or "login rejected")

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
        page = await self._click_link(overview, code)
        if count and not parse_loans(page):
            raise LibraryParseError("loans table not recognized")
        return page

    # ---- cover lookup -----------------------------------------------------

    async def _lookup_covers(self, page: AdisPage, loans: list[Loan]) -> tuple[AdisPage, dict[str, Lookup]]:
        """Search the catalog once per item like a user would (title + shelf mark + library).

        Only a unique hit opens the full record directly; its ISBN and its cover image are taken.
        Anything else (no hit, a result list) gives no ISBN. Errors stop the lookups but never the
        update. Returns the last page (for the logout) and the results.
        """
        results: dict[str, Lookup] = {}
        try:
            if BUTTON_ADVANCED_SEARCH not in page.buttons and BUTTON_TO_OVERVIEW in page.buttons:
                page = await self._click_button(page, BUTTON_TO_OVERVIEW)  # the loans page has no search
            for loan in loans[:MAX_LOOKUPS_PER_UPDATE]:
                page, form = await self._open_search_form(page)
                if form is None:
                    _LOGGER.debug("Advanced search form not recognized")
                    break
                page = await self._search(page, form, loan)
                result = results[loan.barcode] = await self._read_record(page)
                _LOGGER.debug("Cover lookup for %s: %s, cover %s", loan.barcode, result.isbn or "no unique record", bool(result.cover))
        except LibraryError as err:
            _LOGGER.debug("Cover lookup stopped: %s", err)
        return page, results

    async def _open_search_form(self, page: AdisPage) -> tuple[AdisPage, SearchForm | None]:
        """The advanced search form: the current page after a search without hit, otherwise via its button."""
        fields = (SEARCH_FIELD_TITLE, SEARCH_FIELD_SHELF_MARK)
        form = parse_search_form(page, fields, SEARCH_OPERATOR_AND, BUTTON_SEARCH)
        if form is None and BUTTON_ADVANCED_SEARCH in page.buttons:
            page = await self._click_button(page, BUTTON_ADVANCED_SEARCH)
            form = parse_search_form(page, fields, SEARCH_OPERATOR_AND, BUTTON_SEARCH)
        return page, form

    async def _search(self, page: AdisPage, form: SearchForm, loan: Loan) -> AdisPage:
        """Fill in library, title and shelf mark and press the form's own search button."""
        values = dict(form.fields)
        values.update({name: "" for name, _ in form.texts})  # the catalog keeps the terms of the previous search
        values[form.library] = loan.library
        (title_select, title_input), (shelf_select, shelf_input) = form.rows[0], form.rows[1]
        values.update({title_select: SEARCH_FIELD_TITLE, title_input: loan.title, form.operators[0]: SEARCH_OPERATOR_AND})
        if loan.shelf_mark:
            values.update({shelf_select: SEARCH_FIELD_SHELF_MARK, shelf_input: loan.shelf_mark})
        return await self._press(page, form.submit, values)

    async def _read_record(self, page: AdisPage) -> Lookup:
        """ISBN and cover of a full record page; a result list or the search form give no ISBN."""
        isbn = parse_isbn(page)
        if not isbn:
            return Lookup(None)
        image = await self._fetch_image(parse_cover_src(page) or COVER_URL.format(isbn=isbn), page.url)
        return Lookup(isbn, *image) if image else Lookup(isbn)

    # ---- public -----------------------------------------------------------

    async def async_fetch(self, known: set[str] | None = None) -> AccountData:
        """Card validity and current loans.

        known: barcodes searched earlier. None disables lookups; otherwise items not in it are
        searched in the catalog once (results in AccountData.looked_up).
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
                looked_up: dict[str, Lookup] = {}
                if known is not None:
                    new = [loan for loan in loans if loan.barcode not in known]
                    if new:
                        last, looked_up = await self._lookup_covers(last, new)
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

                result_page = await self._click_button(
                    loans_page, BUTTON_RENEW_MARKED, [("$RTable_checkbox[]", before.checkbox)]
                )
                last = result_page
                after_loans = parse_loans(result_page)
                if not after_loans:
                    raise LibraryParseError("loans table not recognized after renewal")
                after = next((loan for loan in after_loans if loan.barcode == barcode), None)
                account = AccountData(valid, after_loans)
                renewed = after is not None and (
                    after.renewed_today
                    or (after.due_date and before.due_date and after.due_date > before.due_date)
                )
                if not renewed:
                    raise LibraryRenewError(after.hint if after else "loan missing after renewal", account)
                return RenewResult(account, after, page_message(result_page))
            finally:
                await self._logout(last)
