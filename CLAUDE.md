# Münchner Stadtbibliothek: notes for Claude

Home Assistant custom integration for the account of the Münchner Stadtbibliothek (card validity, loans, renewal).
This file carries technical context across sessions; keep it current.
This repository is public: never put personal information about the maintainer or his family into any file (no real card numbers, names or borrowed titles, also not in tests).

## Repository layout

```
custom_components/muenchner_stadtbibliothek/
  const.py          constants, catalog URL and all German page texts the client looks for
  models.py         data classes, no HA imports: Loan (loans table + isbn/cover_url), AccountData, Lookup, RenewResult
  parser.py         HTML parsing (BeautifulSoup), no HA imports: forms, link codes, login page, loans table, card validity, search form
  api.py            LibraryClient (aiohttp), no HA imports: one full catalog session per call (login, pages, logout); _press = every button submit
  coordinator.py    DataUpdateCoordinator, renew -> async_set_updated_data with the catalog's answer
  sensor.py         card_valid_until, loans (list in attribute "loans"), next_due_date
  button.py         one renew button per loan, added/removed with the loans (entity registry)
  config_flow.py    one entry per card (unique_id = card number), reauth, options: interval in hours
  diagnostics.py    redacted
  frontend_resource.py  serves frontend/ under /muenchner_stadtbibliothek_files (no-cache) and adds the dashboard resource (?v=VERSION)
  frontend/muenchner-stadtbibliothek-card.js  card + editor (vanilla JS, ha-form editor, de/en texts inline)
tests/fake_adis.py      fake catalog (same HTML structure as the real one, invented data) + FakeSession
tests/test_client.py    python3 tests/test_client.py (needs only beautifulsoup4; stubs aiohttp if missing)
tests/test_integration.py real HA via pytest-homeassistant-custom-component (GitHub Actions only, no PyPI here)
scripts/bump_version.py   sets the version in manifest.json, const.py and the card
scripts/release_notes.py  release notes from commit subjects
```

## How the catalog works (aDIS/BMS by aStec, ssl.muenchen.de)

- Start: `GET /aDISWeb/app?service=direct/0/Home/$DirectLink&sp=SOPAC` -> catalog page with session path `/aDISWeb/_<session>/app`.
- Every page has one form `Form0` with hidden fields (`identity` changes every request, `requestCount`, ...). Always post the hidden fields of the current page.
- Links are `<a id="idfnN">` with a script `function fnN(e){ ... htmlOnLink("<code>") }`. Clicking posts the form with `selected="ZTEXT       <code>"` (ZTEXT + 7 spaces), `keyCode=0`. Known codes: Mein Konto `*SBK`, Sitzung beenden `*SE`, "N Ausleihen" `*SZA` (the client finds codes by link text, not hard coded).
- Buttons are `<input type=submit name="$Button$N">`; N differs between pages, so they are found by their value. The browser sends `name=value`, `name=pressed`, `focus=<data-fld>`, `source=$B`.
- Login: "Mein Konto" redirects to OpenID Connect `/oidcp/authorize`; form posts to `/oidcp/logincheck` with `L#AUSW`, `LPASSW`, `LLOGIN=Anmelden`, then redirects back to the overview.
- Overview: `<dl><dt>Ausweis gültig bis</dt><dd>31.12.2030</dd>...`; loans link text e.g. "3 Ausleihen" (no link when there are none).
- Loans: table `#resptable-1`, columns Markieren | Fällig am | Bibliothek | Titel | Hinweis. Title cell: `title / author ; ...<br>shelf mark<br>barcode`. Checkbox values `CheckCell`, `CheckCell_0`, ... are row positions, not stable.
- Hint examples: "verlängerbar - Stand 02.03.2030" (renewable), after renewal "Heute verlängert<br>1 Verlängerung". Renewed items move to the end of the table. Renewal = check box + "Markierte Medien verlängern"; the result page shows the full table again plus the message "Sie haben versucht, die Leihfrist ...".
- Cover lookup (option `lookup_covers`, default on): once per new item, max 10 per update, after the loans and before the logout.
  - Path: "Zur Übersicht" (the loans page has no search), then per item "Erweiterte Suche".
  - Form: library select `$Select`, rows (field select, then `$Autosuggest$N`), operator selects (UND). Row 1 = Titel + title, row 2 = Signatur + shelf mark. Submit with the form's own "Suchen" (`$Button$5`, not the header `$Button`).
  - Fields are found by their options, not by name (parser.parse_search_form; real structure in tests/fixtures/advanced_search.html).
  - A unique hit opens "Vollanzeige" directly: `<th>Nummer</th>` EAN, `<th>ISBN</th>`. A result list = no cover.
  - Next item: Vollanzeige and result lists have the "Erweiterte Suche" button. A search without hit stays on the search form (no such button; the form keeps the terms incl. the header search field): reuse that form and clear all its text fields first.
  - Cover image: right after a unique hit the client loads `<img src="/vlb/cover/<EAN>/m">` once, with the record page as referer, like a browser. The cover service has hotlink protection: 403 without a catalog referer and also with a referer containing ":443" (the catalog redirects there; `api.browser_url` strips default ports).
  - Errors: a clear answer without image (404/403/no image) counts as "no cover" for good. Timeouts, connection and server errors stop the lookups of this update without storing anything, so the item is searched again at the next update.
  - Storage: covers in `.storage/muenchner_stadtbibliothek_covers/<EAN>.<ext>`, served at `/muenchner_stadtbibliothek_files/covers/<file>` (no auth, cached for a year). Lookups (barcode -> {"isbn", "file"}) per entry in `.storage/muenchner_stadtbibliothek.<entry_id>.isbn` (const.LOOKUP_STORE_KEY; the suffix is historical), kept for good (wish of the maintainer, no cleanup; a book borrowed again needs no search).
- Session timeout 30 minutes. The client logs out after every call. Each page load (with redirects) times out after 10 s; no retries, no artificial pauses, no extra page loads after a renewal (wish of the maintainer: behave like a user).

## Design decisions (do not undo without asking)

- No permanent session: every update and every renewal is one short session, to keep traffic low. Default interval 4 h.
- Buttons of loans that are not renewable stay available and raise an error with the hint, without a request to the catalog.
- Attribute names are English; page texts in const.py are German because the catalog is German only.
- Attribute structure (wish of the maintainer: logical, everything else follows it): the loans sensor holds all data (`loans` list with every field, `renewable_count`, `fetched_at`); next due date: `count`, `titles` (`count` also tells automations this sensor apart from the card validity); renew buttons only `barcode`, `title`, `due_date`, `renewable`, `renewed_today` (button.BUTTON_ATTRIBUTES). No copies of other sensors' states as attributes; automations find the card validity sensor via `device_entities` (date sensor without `count`).
- README and repository description are German (integration for Munich only); code comments, commit subjects and release notes stay English.

## Card (design approved by the maintainer: "D2" cover + ring, mockups on the design canvas)

- One row per loan, top aligned: cover frame 84 x 124 px (image scaled in without cropping, top aligned; no cover or load error: gradient placeholder in a color from the barcode hash with the title bottom aligned, max 3 lines), ring 44 px with remaining days (full ring = `loan_days`, default 28; orange <= 3 days, red + red border when overdue), title (1.08em, 2 lines), author · library (max 2 lines, 1 line in narrow columns; library optional: `show_library`), due date. `show_covers: false` = previous layout without cover (ring 56 px, centered).
- Right side, vertically centered: round 50 px renew button (primary color 18 %) only when `renewable`; green check circle when `renewed_today`; nothing otherwise. Labels only in aria-label/title. No error display in the card (HA shows the error). Narrow columns (< 400 px): cover 60 x 88, ring 36, buttons 44.
- One press at a time: the button is disabled while the press runs (spinning icon) and for 5 s after a failure (red "!"). The coordinator also rejects a second renewal of the same barcode while one runs (any card or device).
- Accounts = devices of the integration with a loans sensor (found via `hass.entities`, `translation_key`); name = device `name_by_user || name` (device name = entry title from the setup field "Name"). Several accounts: pills like in Sleek School Schedule (active one kept per card instance); option `account` (name, case-insensitive, or the loans entity id) fixes one account and shows `title ?? name`.
- The card finds the buttons by `barcode` attribute among the account's entities, the validity sensor by `translation_key`.
- `max_width` (default 640 px, 0 = full width) limits and centers ha-card, e.g. in Bubble Card pop-ups.
- Card validity warning: `card_warn_days` (default 30) orange "· noch N Tage"; <= 7 days or expired red plus a banner above the loans; shown even with `show_card: false`; pills get a dot.
- Options only differ from defaults are stored; the editor keeps all other keys (grid_options etc.).
- For UI changes: render tests with Playwright (mock hass with `entities`/`states`/`callService`, ha-card stub) in light, dark and narrow.

## Release workflow

Same as in ha-sleek-school-schedule: `python3 tests/test_client.py`, `python3 scripts/bump_version.py X.Y.Z`, commit as `Claude <noreply@anthropic.com>` with short neutral subject lines, push to `main`; `release.yml` creates the release. Show the release notes to the maintainer after every release.

## Lessons learned

- 0.1.0 failed in a real HA setup with "not reachable"; 0.1.2 (browser compatible user agent, login button found by field name `LLOGIN`) works. Which of the two was the cause is unknown; keep both.
- The OIDC login page is served in English without `Accept-Language: de` ("Login" instead of "Anmelden"); always send the German header and never rely on button labels where a field name exists.
- No PyPI here (no aiohttp): real catalog checks run through tests/fake_adis.py-style bridges with `requests`, only with invented card numbers.
- HTML copied from a real session for fixtures carries the maintainer's choices (e.g. a preselected library): strip preselections and personal values before committing.
