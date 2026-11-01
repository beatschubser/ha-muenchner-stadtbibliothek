# Münchner Stadtbibliothek: notes for Claude

Home Assistant custom integration for the account of the Münchner Stadtbibliothek (card validity, loans, renewal).
This file carries technical context across sessions; keep it current.
This repository is public: never put personal information about the maintainer or his family into any file (no real card numbers, names or borrowed titles, also not in tests).

## Repository layout

```
custom_components/muenchner_stadtbibliothek/
  const.py          constants, catalog URL and all German page texts the client looks for
  parser.py         HTML parsing (BeautifulSoup), no HA imports: forms, link codes, loans table, card validity
  api.py            LibraryClient (aiohttp), no HA imports: one full catalog session per call (login, pages, logout)
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
- Session timeout 30 minutes. The client logs out after every call.

## Design decisions (do not undo without asking)

- No permanent session: every update and every renewal is one short session, to keep traffic low. Default interval 4 h.
- Buttons of loans that are not renewable stay available and raise an error with the hint, without a request to the catalog.
- Attribute names are English; page texts in const.py are German because the catalog is German only.

## Card (design approved by the maintainer, "C2" one-column tiles)

- One row per loan: ring with remaining days (full ring = `loan_days`, default 28; orange <= 3 days, red + red border when overdue), title (2 lines), author · library, due date.
- Right side: "Verlängern" pill (primary color 18 %) only when `renewable`; green "Heute verlängert" pill when `renewed_today`; nothing otherwise. No error display in the card (HA shows the error). Narrow columns (< 400 px): icon-only pills.
- The card finds the buttons by `barcode` attribute among the integration's entities on the same device as the loans sensor, and the validity sensor by `translation_key`.
- Options only differ from defaults are stored; the editor keeps all other keys (grid_options etc.).
- For UI changes: render tests with Playwright (mock hass with `entities`/`states`/`callService`, ha-card stub) in light, dark and narrow.

## Release workflow

Same as in ha-sleek-school-schedule: `python3 tests/test_client.py`, `python3 scripts/bump_version.py X.Y.Z`, commit as `Claude <noreply@anthropic.com>` with short neutral subject lines, push to `main`; `release.yml` creates the release. Show the release notes to the maintainer after every release.

## Lessons learned

- 0.1.0 failed in a real HA setup with "not reachable"; 0.1.2 (browser compatible user agent, login button found by field name `LLOGIN`) works. Which of the two was the cause is unknown; keep both.
- The OIDC login page is served in English without `Accept-Language: de` ("Login" instead of "Anmelden"); always send the German header and never rely on button labels where a field name exists.
- No PyPI here (no aiohttp): real catalog checks run through tests/fake_adis.py-style bridges with `requests`, only with invented card numbers.
