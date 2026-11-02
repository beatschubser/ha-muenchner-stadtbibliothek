"""Constants for the Münchner Stadtbibliothek integration."""

from __future__ import annotations

DOMAIN = "muenchner_stadtbibliothek"
VERSION = "0.6.1"

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
BUTTON_LOGIN_NAME = "LLOGIN"  # the label is "Login" when the page is served in English
BUTTON_RENEW_MARKED = "Markierte Medien verlängern"
TERM_CARD_VALID = "Ausweis gültig bis"
COLUMN_DUE = "Fällig am"
COLUMN_LIBRARY = "Bibliothek"
COLUMN_TITLE = "Titel"
COLUMN_HINT = "Hinweis"
HINT_RENEWABLE = "verlängerbar"
HINT_RENEWED_TODAY = "Heute verlängert"
BUTTON_TO_OVERVIEW = "Zur Übersicht"
BUTTON_ADVANCED_SEARCH = "Erweiterte Suche"
BUTTON_SEARCH = "Suchen"
SEARCH_FIELD_TITLE = "Titel"
SEARCH_FIELD_SIGNATURE = "Signatur"
SEARCH_OPERATOR_AND = "UND"

# Covers: the catalog's own cover service (VLB). It only answers requests coming from a catalog
# page (hotlink protection), so the cover is loaded once right after the full record page, like a
# browser showing that page does, and then stored and served by Home Assistant.
COVER_PATH = "/vlb/cover/"
COVER_URL = DEFAULT_BASE_URL + COVER_PATH + "{isbn}/m"  # fallback when the record page has no image
MAX_COVER_BYTES = 2_000_000
COVER_DIR = f"{DOMAIN}_covers"  # below the .storage folder of Home Assistant
COVER_URL_PATH = "/" + DOMAIN + "_files/covers/{file}"
MAX_LOOKUPS_PER_UPDATE = 10  # catalog searches for new items per update (3 page loads each)
CONF_LOOKUP_COVERS = "lookup_covers"
DEFAULT_LOOKUP_COVERS = True

# Card served by the integration
FRONTEND_URL = f"/{DOMAIN}_files"
CARD_FILE = "muenchner-stadtbibliothek-card.js"
CARD_URL = f"{FRONTEND_URL}/{CARD_FILE}"

# browser compatible prefix, some web application firewalls reject unknown agents
USER_AGENT = f"Mozilla/5.0 (compatible; HomeAssistant-MuenchnerStadtbibliothek/{VERSION})"
REQUEST_TIMEOUT = 10  # seconds per page load (including redirects)
