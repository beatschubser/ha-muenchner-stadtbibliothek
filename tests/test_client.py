"""Tests for parser and client against a fake catalog (no Home Assistant needed).

Run: python3 tests/test_client.py   (or with pytest)
"""

import asyncio
import importlib.util
import sys
import types
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fake_adis import CARD, PASSWORD, FakeAdis, FakeSession  # noqa: E402

try:
    import aiohttp  # noqa: F401
except ImportError:  # the client only needs ClientTimeout and ClientError from aiohttp here
    _stub = types.ModuleType("aiohttp")
    _stub.ClientTimeout = lambda **kwargs: kwargs
    _stub.ClientError = type("ClientError", (Exception,), {})
    _stub.ClientSession = object
    sys.modules["aiohttp"] = _stub

BASE = Path(__file__).resolve().parent.parent / "custom_components" / "muenchner_stadtbibliothek"

# Load const.py, parser.py and api.py as a package without importing Home Assistant
_pkg = types.ModuleType("msb")
_pkg.__path__ = [str(BASE)]
sys.modules["msb"] = _pkg


def _load(name):
    spec = importlib.util.spec_from_file_location(f"msb.{name}", BASE / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[f"msb.{name}"] = module
    spec.loader.exec_module(module)
    return module


const = _load("const")
parser = _load("parser")
api = _load("api")


def run(fake, func, password=PASSWORD):
    client = api.LibraryClient(FakeSession(fake), CARD, password, "https://catalog.test")
    return asyncio.run(func(client))


# ---- parser ------------------------------------------------------------------


def test_parse_loans_and_links():
    fake = FakeAdis(logged_in=True, view="loans")
    page = parser.parse_page(fake.render(), "https://example.org/aDISWeb/x/app/opac/1")
    assert page.action == "https://example.org/aDISWeb/_testsession/app"
    assert page.hidden["identity"] == fake.identity
    assert page.links["Mein Konto"] == "*SBK"
    assert parser.loans_link(page) == ("*SZA", 3)
    assert page.buttons["Markierte Medien verlängern"] == ("$Button$2", "$$GFBO_2")

    loans = parser.parse_loans(page)
    assert [loan.barcode for loan in loans] == ["00000100000001", "00000100000002", "00000100000003"]
    first = loans[0]
    assert first.title == "Der kleine Testdrache"
    assert first.author == "Erika Beispiel"
    assert first.signature == "k BEI"
    assert first.library == "Testbibliothek"
    assert first.due_date == date(2030, 3, 16)
    assert first.renewable is True
    assert first.checkbox == "CheckCell"
    assert loans[1].author is None
    assert loans[2].renewable is False
    assert loans[2].checkbox == "CheckCell_1"


def test_renewed_hint():
    fake = FakeAdis(logged_in=True, view="loans")
    fake.loans[0].hint_lines = ["Heute verlängert", "1 Verlängerung"]
    loan = parser.parse_loans(parser.parse_page(fake.render(), "https://x/"))[0]
    assert loan.hint == "Heute verlängert, 1 Verlängerung"
    assert loan.renewable is False
    assert loan.renewals == 1
    assert parser.renewed_today(loan)


def test_overview_without_loans():
    fake = FakeAdis(logged_in=True, view="overview", loans=[])
    page = parser.parse_page(fake.render(), "https://x/")
    assert parser.parse_card_valid_until(page) == date(2030, 12, 31)
    assert parser.loans_link(page) == (None, 0)


# ---- client ------------------------------------------------------------------


def test_fetch():
    fake = FakeAdis()
    data = run(fake, lambda c: c.async_fetch())
    assert data.card_valid_until == date(2030, 12, 31)
    assert len(data.loans) == 3
    assert not fake.logged_in, "client must log out"
    assert fake.requests == [
        "GET start", "GET /aDISWeb/app/opac",
        "POST app ZTEXT       *SBK", "GET login",
        "POST login", "GET callback", "GET /aDISWeb/_testsession/app/opac/1",
        "POST app ZTEXT       *SZA", "GET /aDISWeb/_testsession/app/opac/2",
        "POST app ZTEXT       *SE", "GET /aDISWeb/_testsession/app/opac/3",
    ]


def test_fetch_without_loans():
    data = run(FakeAdis(loans=[]), lambda c: c.async_fetch())
    assert data.loans == []
    assert data.card_valid_until == date(2030, 12, 31)


def test_wrong_password():
    try:
        run(FakeAdis(), lambda c: c.async_fetch(), password="wrong")
    except api.LibraryAuthError as err:
        assert "falsch" in str(err)
    else:
        raise AssertionError("LibraryAuthError expected")


def test_renew():
    fake = FakeAdis()
    result = run(fake, lambda c: c.async_renew("00000100000002"))
    assert result.loan.due_date == date(2030, 3, 30)
    assert result.loan.renewals == 1
    assert result.account.loans[-1].barcode == "00000100000002"
    assert result.message.startswith("Sie haben versucht")
    assert fake.renew_posts == 1
    assert not fake.logged_in


def test_renew_not_renewable():
    fake = FakeAdis()
    try:
        run(fake, lambda c: c.async_renew("00000100000003"))
    except api.LibraryRenewError as err:
        assert "vorgemerkt" in str(err)
    else:
        raise AssertionError("LibraryRenewError expected")
    assert fake.renew_posts == 0
    assert not fake.logged_in


def test_renew_unknown_barcode():
    try:
        run(FakeAdis(), lambda c: c.async_renew("999"))
    except api.LibraryRenewError:
        pass
    else:
        raise AssertionError("LibraryRenewError expected")


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_")]
    for name, func in tests:
        func()
        print(f"ok  {name}")
    print(f"{len(tests)} tests passed")
