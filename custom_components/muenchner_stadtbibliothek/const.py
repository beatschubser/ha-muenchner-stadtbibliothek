"""Constants for the Münchner Stadtbibliothek integration."""

from __future__ import annotations

DOMAIN = "muenchner_stadtbibliothek"
VERSION = "0.1.0"

# Library catalog (aDIS/BMS by aStec). Changeable in case the library moves the catalog.
DEFAULT_BASE_URL = "https://ssl.muenchen.de"
START_PATH = "/aDISWeb/app?service=direct/0/Home/$DirectLink&sp=SOPAC"

CONF_CARD_NUMBER = "card_number"
CONF_SCAN_INTERVAL_HOURS = "scan_interval_hours"

DEFAULT_SCAN_INTERVAL_HOURS = 4
MIN_SCAN_INTERVAL_HOURS = 1
MAX_SCAN_INTERVAL_HOURS = 48

# Texts of the catalog pages the client looks for (German catalog only).
LINK_ACCOUNT = "Mein Konto"
LINK_LOGOUT = "Sitzung beenden"
LINK_LOANS_PATTERN = r"^\s*(\d+)\s+Ausleihe(n)?\s*$"
BUTTON_LOGIN = "Anmelden"
BUTTON_RENEW_MARKED = "Markierte Medien verlängern"
TERM_CARD_VALID = "Ausweis gültig bis"
COLUMN_DUE = "Fällig am"
COLUMN_LIBRARY = "Bibliothek"
COLUMN_TITLE = "Titel"
COLUMN_HINT = "Hinweis"
HINT_RENEWABLE = "verlängerbar"
HINT_RENEWED_TODAY = "Heute verlängert"

USER_AGENT = f"HomeAssistant-MuenchnerStadtbibliothek/{VERSION}"
REQUEST_TIMEOUT = 30
