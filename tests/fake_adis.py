"""Small fake of the aDIS catalog for tests (aiohttp web server).

The HTML follows the structure of the real pages (form Form0, hidden fields,
idfnN links bound to fnN handlers, rTable loans table, OpenID Connect login form).
All names, numbers and titles are invented.
"""

from __future__ import annotations

import html
import secrets
from dataclasses import dataclass, field
from datetime import date, timedelta
from urllib.parse import parse_qs, urlsplit

CARD = "123456789012"
PASSWORD = "secret"
SESSION = "_testsession"

LINKS = {"Mein Konto": "*SBK", "Sitzung beenden": "*SE"}

# Catalog records for the cover lookup: (title, shelf mark, library) -> list of EANs (one = unique hit)
RECORDS = {
    ("Der kleine Testdrache", "k BEI", "Testbibliothek"): ["9783000000002"],
    ("Kochen ohne Herd", "u KOC", "Testbibliothek"): ["9783000000019", "9783000000026"],  # two editions: no unique hit
}
LIBRARIES = ["Bitte auswählen", "Allach", "Bogenhausen", "Giesing", "Hadern", "Laim", "Moosach", "Pasing", "Riem", "Sendling", "Testbibliothek", "Westend"]
FIELDS = ["", "ISBN, ISSN, ISMN", "Person", "Signatur", "Titel"]


@dataclass
class FakeLoan:
    barcode: str
    title: str
    signature: str
    due: date
    hint_lines: list[str]


def default_loans() -> list[FakeLoan]:
    return [
        FakeLoan("00000100000001", "Der kleine Testdrache / Erika Beispiel ; Bilder von Max Muster", "k BEI", date(2030, 3, 16), ["verlängerbar - Stand 02.03.2030"]),
        FakeLoan("00000100000002", "Kochen ohne Herd", "u KOC", date(2030, 3, 16), ["verlängerbar - Stand 02.03.2030"]),
        FakeLoan("00000100000003", "Reise zum Mond / Paul Probe", "b PRO", date(2030, 3, 22), ["nicht verlängerbar, vorgemerkt"]),
    ]


@dataclass
class FakeAdis:
    loans: list[FakeLoan] = field(default_factory=default_loans)
    valid_until: date = date(2030, 12, 31)
    logged_in: bool = False
    view: str = "catalog"
    identity: str = ""
    count: int = 0
    message: str = ""
    requests: list[str] = field(default_factory=list)
    renew_posts: int = 0
    searches: list[tuple[str, str, str]] = field(default_factory=list)
    cover_requests: list[tuple[str, str]] = field(default_factory=list)  # (path, referer)
    last_terms: tuple[str, str] = ("", "")
    cover_failures: int = 0  # number of cover requests answered with a server error (temporary problem)
    hits: list[str] = field(default_factory=list)

    # ---- rendering ----------------------------------------------------------

    def _links(self) -> dict[str, str]:
        links = dict(LINKS)
        if self.logged_in:
            links[f"{len(self.loans)} Ausleihen" if self.loans else "Keine Ausleihen"] = "*SZA"
        return links

    def _page(self, title: str, body: str, buttons: list[str]) -> str:
        self.identity = secrets.token_urlsafe(12)
        self.count += 1
        links = self._links()
        anchors, fns, binds = [], [], []
        for i, (label, code) in enumerate(links.items(), start=2):
            if label == "Keine Ausleihen":
                anchors.append(f"<li>{label}</li>")
                continue
            anchors.append(f'<li><a href="#" id="idfn{i}">{html.escape(label)}</a></li>')
            fns.append(f'function fn{i}(e){{ e.preventDefault(); top.htmlOnLink("{code}");}}')
            binds.append(f'document.getElementById("idfn{i}")?.addEventListener("click", fn{i}, false);')
        btns = "".join(
            f'<input type="submit" value="{html.escape(b)}" id="$$GFBO_{n}" name="$Button${n}" data-fld="$$GFBO_{n}">'
            for n, b in enumerate(buttons)
        )
        return f"""<!DOCTYPE html><html><head><title>{title}</title>
<script src="/aDISWeb/js/aDISMain.min.js"></script>
<script>function adisInit(){{ {' '.join(binds)} }} {' '.join(fns)}</script></head>
<body><form name="Form0" method="post" action="/aDISWeb/{SESSION}/app">
<input type="hidden" name="identity" value="{self.identity}">
<input type="hidden" name="keyCode" value="0"><input type="hidden" name="focus" value="">
<input type="hidden" name="source" value=""><input type="hidden" name="selected" value="">
<input type="hidden" name="requestCount" value="{self.count}"><input type="hidden" name="scrollPos" value="0">
<nav><ul>{''.join(anchors)}</ul></nav><main>{body}</main>{btns}</form></body></html>"""

    def render(self) -> str:
        if self.view == "overview":
            body = f"""<p>Hallo Erika Beispiel - {CARD}</p><dl>
<dt class="adis-term">Ausweis gültig bis</dt><dd class="adis-value">{self.valid_until:%d.%m.%Y}</dd>
<dt class="adis-term">Kontostand vom:</dt><dd class="adis-value">Datum: 02.03.2030 Uhrzeit: 10:00</dd></dl>"""
            return self._page("Mein Konto - Katalog", body, ["Suchen", "Erweiterte Suche", "Druckversion"])
        if self.view == "loans":
            rows = []
            for i, loan in enumerate(self.loans):
                value = "CheckCell" if i == 0 else f"CheckCell_{i - 1}"
                rows.append(
                    f'<tr><td><input type="checkbox" name="$RTable_checkbox[]" value="{value}" id="{value}"></td>'
                    f"<td>{loan.due:%d.%m.%Y}</td><td>Testbibliothek</td>"
                    f"<td>{html.escape(loan.title)}<br>{loan.signature}<br>{loan.barcode}</td>"
                    f"<td>{'<br>'.join(loan.hint_lines)}</td></tr>"
                )
            body = f"""<p>{self.message}</p><table class="rTable_table" id="resptable-1"><thead><tr>
<th><span class="invisible">Markieren</span></th><th>Fällig am</th><th>Bibliothek</th><th>Titel</th><th>Hinweis</th>
</tr></thead><tbody>{''.join(rows)}</tbody></table>"""
            return self._page("Meine Ausleihen - Katalog", body, ["Druckversion", "Alle verlängern", "Markierte Medien verlängern", "Zur Übersicht"])
        if self.view == "advanced":
            return self._page("Erweiterte Suche - Katalog", self._advanced_form(self.last_terms), ["Suchen", "Wiederholen", "Leeren", "Suchen"])
        if self.view == "record":
            ean = self.hits[0]
            body = f"""<table><tr><th scope="row">Titel</th><td>Testtitel</td></tr>
<tr><th scope="row">ISBN</th><td>{ean[3:6]}-{ean[6:12]}-{ean[12]} <br> {ean[3:12]}X</td></tr>
<tr><th scope="row">Nummer</th><td>{ean} (Europäische Artikelnummerierung (EAN))</td></tr></table>
<aside><img src="/aDISWeb_kopac86/img/medien/buch.svg" alt="Buch"><img src="/vlb/cover/{ean}/m" alt=""></aside>"""
            return self._page("Vollanzeige - Katalog", body, ["Suchen", "Erweiterte Suche", "Bestellen/Vormerken"])
        if self.view == "results":
            body = f"<p>Treffer: {len(self.hits)}</p>" + "".join(f"<div>Treffer {n}</div>" for n in range(len(self.hits)))
            return self._page("Trefferliste - Katalog", body, ["Suchen", "Erweiterte Suche"])
        return self._page("Katalog", "<p>Suche</p>", ["Suchen"])

    @staticmethod
    def _advanced_form(terms: tuple[str, str] = ("", "")) -> str:
        def select(name, options, chosen=""):
            opts = "".join(f'<option value="{html.escape(o)}"{" selected" if o == chosen else ""}>{html.escape(o)}</option>' for o in options)
            return f'<select name="{name}">{opts}</select>'

        rows = []
        for n, chosen in enumerate(["Titel", "Person", "ISBN, ISSN, ISMN"]):
            value = html.escape(terms[n]) if n < 2 else ""
            rows.append(select(f"$Select${2 * n}", FIELDS, chosen) + f'<input type="search" name="$Autosuggest${n}" value="{value}">')
            if n < 2:
                rows.append(select(f"$Select${2 * n + 1}", ["", "NICHT", "ODER", "UND"], "UND"))
        return (
            f'<input type="search" name="$Autosuggest" value="{html.escape(terms[0])}">'
            + select("$Select", LIBRARIES, "Bitte auswählen")
            + "".join(rows)
            + select("$Select$5", ["- Alle -", "Buch", "CD", "DVD-Video", "Spiel", "E-Book", "Noten", "Karte", "LP", "Video", "Zeitung", "Zeitschriften"], "- Alle -")
            + '<input type="text" name="$Textfield$0" value="">'
        )

    # ---- requests -------------------------------------------------------------

    def handle(self, method: str, url: str, data: list[tuple[str, str]] | None = None, headers: dict | None = None) -> tuple[int, str | bytes]:
        """Answer one request: (302/303, location) or (200, html)."""
        parts = urlsplit(url)
        path, query = parts.path, parse_qs(parts.query)
        if method == "GET" and path.startswith("/vlb/cover/"):
            # like the real cover service: only for requests coming from a catalog page
            referer = (headers or {}).get("Referer", "")
            self.cover_requests.append((path, referer))
            if "/aDISWeb/" not in referer:
                return 403, "<html>Forbidden</html>"
            if self.cover_failures:
                self.cover_failures -= 1
                return 503, "<html>Service Unavailable</html>"
            return 200, b"\xff\xd8\xff\xe0fake-jpeg-" + path.encode()
        form: dict[str, list[str]] = {}
        for key, value in data or []:
            form.setdefault(key, []).append(value)
        first = lambda key: form.get(key, [""])[0]  # noqa: E731

        if method == "GET" and path == "/aDISWeb/app":
            self.requests.append("GET start")
            self.logged_in, self.view = False, "catalog"
            return 302, "/aDISWeb/app/opac"
        if method == "GET" and (path == "/aDISWeb/app/opac" or path.startswith(f"/aDISWeb/{SESSION}/app/opac/")):
            self.requests.append(f"GET {path}")
            return 200, self.render()
        if method == "POST" and path == f"/aDISWeb/{SESSION}/app":
            self.requests.append(f"POST app {first('selected').strip() or first('source')}")
            if first("identity") != self.identity:
                return 200, "<html>Sitzung abgelaufen</html>"
            return self._post(form)
        if method == "GET" and path == "/oidcp/authorize":
            self.requests.append("GET login")
            return 200, self._login_page(bool(query.get("error")))
        if method == "POST" and path == "/oidcp/logincheck":
            self.requests.append("POST login")
            if first("L#AUSW") != CARD or first("LPASSW") != PASSWORD or first("LLOGIN") != "Anmelden":
                return 303, "/oidcp/authorize?client_id=opac001&error=1"
            self.logged_in, self.view = True, "overview"
            return 303, "/aDISWeb/callback?code=x"
        if method == "GET" and path == "/aDISWeb/callback":
            self.requests.append("GET callback")
            return 303, f"/aDISWeb/{SESSION}/app/opac/{self.count}"
        return 404, "not found"

    def _post(self, form: dict[str, list[str]]) -> tuple[int, str]:
        selected = form.get("selected", [""])[0]
        self.message = ""
        if selected:
            assert selected.startswith("ZTEXT       "), selected
            code = selected[12:]
            if code == "*SBK":
                if not self.logged_in:
                    return 303, "/oidcp/authorize?client_id=opac001"
                self.view = "overview"
            elif code == "*SZA" and self.logged_in:
                self.view = "loans"
            elif code == "*SE":
                self.logged_in, self.view = False, "catalog"
        elif self._pressed(form, "Erweiterte Suche"):
            self.view = "advanced"
        elif self._pressed(form, "Zur Übersicht"):
            self.view = "overview"
        elif self.view == "advanced" and "pressed" in form.get("$Button$3", []):
            first = lambda key: form.get(key, [""])[0]  # noqa: E731
            assert first("$Select$0") == "Titel" and first("$Select$1") == "UND", form
            assert first("$Autosuggest") == "", "old search terms must not be sent again"
            title = first("$Autosuggest$0")
            signature = first("$Autosuggest$1") if first("$Select$2") == "Signatur" else ""
            library = first("$Select")
            self.searches.append((title, signature, library))
            self.hits = RECORDS.get((title, signature, library), [])
            self.last_terms = (title, signature)
            # like the real catalog: one hit -> record, several -> list, none -> the form again (terms kept)
            self.view = "record" if len(self.hits) == 1 else "results" if self.hits else "advanced"
        elif "Markierte Medien verlängern" in form.get("$Button$2", []):
            assert "pressed" in form["$Button$2"], "button marker missing"
            self.renew_posts += 1
            values = ["CheckCell" if i == 0 else f"CheckCell_{i - 1}" for i in range(len(self.loans))]
            renewed = [self.loans[values.index(v)] for v in form.get("$RTable_checkbox[]", []) if v in values]
            for loan in renewed:
                if loan.hint_lines[0].startswith("verlängerbar"):
                    loan.due += timedelta(days=14)
                    loan.hint_lines = ["Heute verlängert", "1 Verlängerung"]
                    self.loans.remove(loan)
                    self.loans.append(loan)  # the real catalog moves renewed items to the end
            self.message = 'Sie haben versucht, die Leihfrist von Medien zu verlängern. Beachten Sie bitte die Spalte "Hinweis".'
        return 303, f"/aDISWeb/{SESSION}/app/opac/{self.count}"

    @staticmethod
    def _pressed(form: dict[str, list[str]], label: str) -> bool:
        return any(label in values and "pressed" in values for key, values in form.items() if key.startswith("$Button"))

    @staticmethod
    def _login_page(error: bool) -> str:
        message = '<div class="error">Ausweisnummer oder Passwort falsch</div>' if error else ""
        return f"""<html><body>{message}<form method="post" action="/oidcp/logincheck">
<label for="a">Ausweisnummer:</label><input type="text" name="L#AUSW" id="a">
<label for="p">Passwort:</label><input type="password" name="LPASSW" id="p">
<input type="submit" name="LLOGIN" value="Anmelden"><input type="submit" name="LCANCL" value="Abbrechen">
</form></body></html>"""


class _Response:
    def __init__(self, status: int, body: str | bytes, url: str) -> None:
        self.status, self._body = status, body
        self.url = _Url(url)
        self.content_type = "image/jpeg" if isinstance(body, bytes) else "text/html"
        self.reason = "OK" if status == 200 else "Error"

    async def text(self) -> str:
        return self._body if isinstance(self._body, str) else self._body.decode("latin-1")

    async def read(self) -> bytes:
        return self._body if isinstance(self._body, bytes) else self._body.encode()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc) -> None:
        return None


class _Url(str):
    @property
    def path(self) -> str:
        return urlsplit(self).path


class _CookieJar:
    def clear(self) -> None:
        return None


class FakeSession:
    """Stands in for aiohttp.ClientSession: follows redirects like aiohttp (303 -> GET)."""

    def __init__(self, fake: FakeAdis, base: str = "https://catalog.test") -> None:
        self.fake, self.base = fake, base
        self.cookie_jar = _CookieJar()

    def request(self, method, url, data=None, headers=None, **_kwargs) -> _Response:
        if url.startswith("/"):
            url = self.base + url
        for _ in range(10):
            status, body = self.fake.handle(method, url, list(data or []), headers)
            if status in (301, 302, 303):
                url, method, data = self.base + body, "GET", None
                continue
            return _Response(status, body, url)
        raise RuntimeError("too many redirects")
