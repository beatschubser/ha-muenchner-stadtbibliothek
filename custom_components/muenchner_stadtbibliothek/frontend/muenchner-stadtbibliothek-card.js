/*
 * Münchner Stadtbibliothek card: current loans with remaining days and renewal.
 * Served by the integration (no build step, no external libraries).
 *
 * Card options (all optional, editable in the visual editor):
 *   account     name of one library card (as set up in the integration); default: all cards as pills
 *   title       heading when only one card is shown (default: its name)
 *   show_card   show "card valid until" in the header (default: true)
 *   show_library  show the library next to the author (default: true)
 *   max_width   maximum width in px, centered (default: 640, 0 = full width)
 *   show_covers show the cover of each item (default: true; placeholder with the title when none was found)
 *   card_warn_days  warn this many days before the card expires (default: 30; red from 7 days)
 *   loan_days   loan period in days, full ring (default: 28)
 *   appearance  auto | light | dark (default: auto = theme)
 */

const VERSION = "1.0.2";
const DOMAIN = "muenchner_stadtbibliothek";
const CARD_TYPE = "muenchner-stadtbibliothek-card";
const DEFAULT_LOAN_DAYS = 28;
const DEFAULT_MAX_WIDTH = 640; // px; the card stays readable in wide pop-ups and panels (0 = no limit)
const SOON_DAYS = 3; // remaining days shown in the warning color
const DEFAULT_CARD_WARN_DAYS = 30; // card validity shown in the warning color from here
const CARD_ALERT_DAYS = 7; // red, plus a banner above the loans
const FAILED_LOCK_MS = 5000; // a failed renewal keeps its button locked this long
const APPEARANCES = ["auto", "light", "dark"];
const ALL = "__all__"; // editor value for "all accounts as pills"

const TEXTS = {
  de: {
    card_valid: "Ausweis gültig bis {date}",
    card_left: "noch {n} Tage",
    card_left_one: "noch 1 Tag",
    card_left_today: "läuft heute ab",
    card_expired: "Ausweis abgelaufen seit {date}",
    card_alert: "Der Ausweis läuft in {n} Tagen ab.",
    card_alert_one: "Der Ausweis läuft morgen ab.",
    card_alert_today: "Der Ausweis läuft heute ab.",
    card_alert_expired: "Der Ausweis ist abgelaufen.",
    card_warning: "Ausweis läuft bald ab",
    due: "fällig {date}",
    overdue: "überfällig seit {date}",
    days_left: "noch {n} Tage",
    day_left: "noch 1 Tag",
    today: "heute fällig",
    overdue_short: "überfällig",
    renew: "Verlängern",
    renew_label: "{title} verlängern",
    renewing: "Verlängere …",
    failed: "Fehlgeschlagen",
    renewed: "Heute verlängert",
    empty: "Keine Ausleihen",
    unavailable: "Keine Daten",
    no_entity: "Kein Ausweis der Integration Münchner Stadtbibliothek gefunden.",
    account_not_found: "Ausweis „{name}“ nicht gefunden.",
    editor_account: "Ausweis",
    editor_all: "Alle (als Auswahl-Pillen)",
    editor_title: "Titel (leer = Name des Ausweises)",
    editor_show_card: "Ausweis-Gültigkeit anzeigen",
    editor_show_library: "Bibliothek anzeigen",
    editor_show_covers: "Cover anzeigen",
    editor_card_warn_days: "Warnung vor Ablauf des Ausweises (Tage)",
    editor_max_width: "Maximale Breite (px, 0 = volle Breite)",
    editor_loan_days: "Leihfrist (Tage, voller Ring)",
    editor_appearance: "Darstellung",
    appearance_auto: "Wie Theme",
    appearance_light: "Hell",
    appearance_dark: "Dunkel",
  },
  en: {
    card_valid: "Card valid until {date}",
    card_left: "{n} days left",
    card_left_one: "1 day left",
    card_left_today: "expires today",
    card_expired: "Card expired on {date}",
    card_alert: "The library card expires in {n} days.",
    card_alert_one: "The library card expires tomorrow.",
    card_alert_today: "The library card expires today.",
    card_alert_expired: "The library card has expired.",
    card_warning: "Card expires soon",
    due: "due {date}",
    overdue: "overdue since {date}",
    days_left: "{n} days left",
    day_left: "1 day left",
    today: "due today",
    overdue_short: "overdue",
    renew: "Renew",
    renew_label: "Renew {title}",
    renewing: "Renewing …",
    failed: "Failed",
    renewed: "Renewed today",
    empty: "No loans",
    unavailable: "No data",
    no_entity: "No library card of the Münchner Stadtbibliothek integration found.",
    account_not_found: "Library card \"{name}\" not found.",
    editor_account: "Library card",
    editor_all: "All (as selection pills)",
    editor_title: "Title (empty = name of the card)",
    editor_show_card: "Show card validity",
    editor_show_library: "Show library",
    editor_show_covers: "Show covers",
    editor_card_warn_days: "Warn before the card expires (days)",
    editor_max_width: "Maximum width (px, 0 = full width)",
    editor_loan_days: "Loan period (days, full ring)",
    editor_appearance: "Appearance",
    appearance_auto: "Like theme",
    appearance_light: "Light",
    appearance_dark: "Dark",
  },
};

function language(hass) {
  const lang = (hass?.locale?.language || hass?.language || "en").split("-")[0];
  return TEXTS[lang] ? lang : "en";
}

function t(hass, key, vars = {}) {
  const text = TEXTS[language(hass)][key] ?? TEXTS.en[key] ?? key;
  return text.replace(/\{(\w+)\}/g, (_, name) => (name in vars ? vars[name] : `{${name}}`));
}

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}

/** Local date (YYYY-MM-DD) to a Date at local midnight. */
function parseDate(iso) {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso || "");
  return m ? new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3])) : null;
}

function daysUntil(date) {
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  return Math.round((date - today) / 86400000);
}

function formatDate(hass, date, withYear = false) {
  const lang = hass?.locale?.language || "de";
  try {
    if (withYear) return new Intl.DateTimeFormat(lang, { day: "2-digit", month: "2-digit", year: "numeric" }).format(date);
    // "Di 03.11." (short weekday without its trailing dot, then day and month)
    const weekday = new Intl.DateTimeFormat(lang, { weekday: "short" }).format(date).replace(/\.$/, "");
    const dayMonth = new Intl.DateTimeFormat(lang, { day: "2-digit", month: "2-digit" }).format(date);
    return `${weekday} ${dayMonth}${/\d$/.test(dayMonth) && lang.startsWith("de") ? "." : ""}`;
  } catch (e) {
    return date.toLocaleDateString();
  }
}

/** All entities of the integration (entity registry entries the frontend knows). */
function integrationEntities(hass) {
  return Object.values(hass?.entities || {}).filter((e) => e.platform === DOMAIN);
}

/**
 * One account per library card (= device of the integration): name, loans sensor,
 * validity sensor and the renew buttons by barcode. Sorted by name.
 */
function findAccounts(hass) {
  const byDevice = {};
  for (const e of integrationEntities(hass)) {
    const key = e.device_id || e.entity_id;
    const account = (byDevice[key] ||= { id: key, loans: null, validity: null, buttons: {} });
    if (e.entity_id.startsWith("sensor.") && e.translation_key === "loans") account.loans = e.entity_id;
    else if (e.entity_id.startsWith("sensor.") && e.translation_key === "card_valid_until") account.validity = e.entity_id;
    else if (e.entity_id.startsWith("button.")) {
      const barcode = hass.states[e.entity_id]?.attributes?.barcode;
      if (barcode) account.buttons[barcode] = e.entity_id;
    }
  }
  return Object.values(byDevice)
    .filter((a) => a.loans)
    .map((a) => {
      const device = hass.devices?.[a.id];
      return { ...a, name: device?.name_by_user || device?.name || hass.states[a.loans]?.attributes?.friendly_name || a.loans };
    })
    .sort((a, b) => a.name.localeCompare(b.name));
}

/** account option: name (case-insensitive) or entity id of the loans sensor */
const matchAccount = (account, wanted) =>
  account.loans === wanted || account.name.toLowerCase() === String(wanted).trim().toLowerCase();

const RENEW_ICON =
  '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 12a9 9 0 1 1-3-6.7"></path><path d="M21 4v5h-5"></path></svg>';
const DONE_ICON =
  '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20 6 9 17l-5-5"></path></svg>';
const FAILED_ICON =
  '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 7v6"></path><path d="M12 17h.01"></path></svg>';
// placeholder covers: one of these colors per item, always the same for the same item
const PLACEHOLDER_COLORS = ["#8e5b9a", "#3d7ea6", "#a0623a", "#4a8a5c", "#9a4a5a", "#5a6fa8", "#8a7a3a", "#3a8a8a"];

function hashCode(text) {
  let h = 0;
  for (const ch of String(text)) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  return h;
}

const RING_RADIUS = 23;
const RING_LENGTH = 2 * Math.PI * RING_RADIUS;
const RING_STROKE = 6;
const RING_GAP = 6; // minimum visible gap between the round ends of a partial ring

/** stroke-dasharray for a share of the ring. Round caps add half the stroke at each end, so they are
 *  subtracted; a nearly full ring keeps a clear gap, a full ring is drawn closed (class "full"). */
function ringDash(share) {
  if (share >= 1) return { dash: `${RING_LENGTH.toFixed(1)} 0`, full: true };
  const length = Math.min(share * RING_LENGTH - RING_STROKE, RING_LENGTH - RING_STROKE - RING_GAP);
  return { dash: `${Math.max(0.01, length).toFixed(1)} ${RING_LENGTH.toFixed(1)}`, full: false };
}

/* =====================================================================
 * Card
 * ===================================================================== */

class MuenchnerStadtbibliothekCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" }).innerHTML = `<style>${CARD_STYLE}</style><ha-card></ha-card>`;
    this._card = this.shadowRoot.querySelector("ha-card");
    this._card.addEventListener("click", (e) => this._onClick(e));
    this._config = {};
    this._pending = new Set(); // barcodes being renewed right now
    this._failed = new Map(); // barcode -> timer of the lock after a failed renewal
    this._brokenCovers = new Set(); // cover urls that did not load: placeholder instead
    // img errors do not bubble; catch them on the way down
    this._card.addEventListener(
      "error",
      (e) => {
        const url = e.target?.dataset?.cover;
        if (url && !this._brokenCovers.has(url)) {
          this._brokenCovers.add(url);
          this._render();
        }
      },
      true
    );
    this._active = null; // id of the account shown when there are pills
    this._size = 3;
  }

  static getConfigElement() {
    return document.createElement(`${CARD_TYPE}-editor`);
  }

  static getStubConfig() {
    return {};
  }

  setConfig(config) {
    this._config = { ...(config || {}) };
    this._signature = null;
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    // Only render when something the card shows has changed
    const signature = this._signatureOf(hass);
    if (signature !== this._signature) {
      this._signature = signature;
      this._render();
    }
  }

  getCardSize() {
    return this._size;
  }

  getGridOptions() {
    return { columns: 12, min_columns: 6, rows: "auto" };
  }

  _signatureOf(hass) {
    const parts = integrationEntities(hass).map((e) => {
      const state = hass.states[e.entity_id];
      return `${e.entity_id}=${state?.state}:${state?.attributes?.barcode || ""}:${JSON.stringify(state?.attributes?.loans || "")}`;
    });
    const names = Object.values(hass.devices || {})
      .map((d) => `${d.id}:${d.name_by_user || d.name}`)
      .join(",");
    return [parts.join(","), names, language(hass), new Date().toDateString()].join("|");
  }

  /** Accounts this card shows: one fixed account (option account) or all. */
  _accounts() {
    const all = findAccounts(this._hass);
    const wanted = this._config.account;
    return wanted ? all.filter((a) => matchAccount(a, wanted)) : all;
  }

  _loans(account) {
    const state = this._hass.states[account.loans];
    const loans = Array.isArray(state?.attributes?.loans) ? state.attributes.loans : null;
    if (!loans) return null;
    const period = Number(this._config.loan_days) > 0 ? Number(this._config.loan_days) : DEFAULT_LOAN_DAYS;
    return loans
      .map((loan) => {
        const due = parseDate(loan.due_date);
        const days = due ? daysUntil(due) : null;
        return { ...loan, due, days, renewedToday: loan.renewed_today === true, period };
      })
      .sort((a, b) => (a.days ?? 9999) - (b.days ?? 9999) || String(a.title).localeCompare(String(b.title)));
  }

  _render() {
    if (!this._hass) return;
    const hass = this._hass;
    const appearance = APPEARANCES.includes(this._config.appearance) ? this._config.appearance : "auto";
    this._card.className = appearance === "auto" ? "" : `mode-${appearance}`;
    this._card.lang = hass.locale?.language || hass.language || "de"; // for hyphenation of titles
    const maxWidth = Number(this._config.max_width ?? DEFAULT_MAX_WIDTH);
    this._card.style.maxWidth = maxWidth > 0 ? `${maxWidth}px` : "";

    const accounts = this._accounts();
    if (!accounts.length) {
      this._size = 2;
      const wanted = this._config.account;
      this._card.innerHTML = `<div class="message">${esc(wanted ? t(hass, "account_not_found", { name: wanted }) : t(hass, "no_entity"))}</div>`;
      return;
    }
    const account = accounts.find((a) => a.id === this._active) || accounts[0];
    this._active = account.id;

    const card = this._cardStatus(account);
    // the validity is always shown while a warning is due, even with show_card off
    let valid = "";
    if (card && (this._config.show_card !== false || card.level !== "ok")) {
      const date = formatDate(hass, card.date, true);
      const left = card.days === 0 ? t(hass, "card_left_today") : card.days === 1 ? t(hass, "card_left_one") : t(hass, "card_left", { n: card.days });
      const text = card.level === "expired" ? t(hass, "card_expired", { date }) : card.level === "ok" ? t(hass, "card_valid", { date }) : `${t(hass, "card_valid", { date })} · ${left}`;
      valid = `<div class="valid ${card.level}">${esc(text)}</div>`;
    }
    let banner = "";
    if (card && (card.level === "alert" || card.level === "expired")) {
      const text =
        card.level === "expired" ? t(hass, "card_alert_expired") : card.days === 0 ? t(hass, "card_alert_today") : card.days === 1 ? t(hass, "card_alert_one") : t(hass, "card_alert", { n: card.days });
      banner = `<div class="banner" role="alert">${esc(text)}</div>`;
    }
    let head;
    if (accounts.length > 1) {
      const pills = accounts
        .map(
          (a) =>
            `<button type="button" class="tab ${a.id === account.id ? "active" : ""}" data-tab="${esc(a.id)}" aria-pressed="${a.id === account.id}">${esc(a.name)}${this._pillDot(a)}</button>`
        )
        .join("");
      head = `<div class="head"><div class="tabs">${pills}</div>${valid}</div>`;
    } else {
      const title = this._config.title ?? account.name;
      head = title || valid ? `<div class="head"><div class="title">${esc(title)}</div>${valid}</div>` : "";
    }

    const loans = this._loans(account);
    let body;
    if (loans === null) {
      body = `<div class="message">${esc(t(hass, "unavailable"))}</div>`;
    } else if (loans.length === 0) {
      body = `<div class="message">${esc(t(hass, "empty"))}</div>`;
    } else {
      body = `<div class="list">${loans.map((loan) => this._row(loan, account.buttons[loan.barcode])).join("")}</div>`;
    }
    this._size = 1 + Math.max(1, Math.ceil((loans?.length || 1) * 1.6));
    this._card.innerHTML = head + banner + body;
  }

  /** Validity of an account's library card: date, remaining days and warning level. */
  _cardStatus(account) {
    const state = account.validity ? this._hass.states[account.validity] : null;
    const date = state && parseDate(state.state);
    if (!date) return null;
    const days = daysUntil(date);
    const warn = Number(this._config.card_warn_days ?? DEFAULT_CARD_WARN_DAYS);
    const level = days < 0 ? "expired" : days <= CARD_ALERT_DAYS ? "alert" : days <= warn ? "warn" : "ok";
    return { date, days, level };
  }

  /** Small dot on a pill whose library card expires soon (it may not be the one shown). */
  _pillDot(account) {
    const card = this._cardStatus(account);
    if (!card || card.level === "ok") return "";
    return `<span class="dot ${card.level}" role="img" aria-label="${esc(t(this._hass, "card_warning"))}"></span>`;
  }

  _row(loan, buttonId) {
    const hass = this._hass;
    const overdue = loan.days !== null && loan.days < 0;
    const tone = overdue ? "overdue" : loan.days !== null && loan.days <= SOON_DAYS ? "soon" : "normal";
    const ring = ringDash(overdue ? 1 : Math.max(0, Math.min(1, (loan.days ?? 0) / loan.period)));
    const ringText = overdue ? "!" : loan.days ?? "?";
    const ringLabel =
      loan.days === null ? "" : overdue ? t(hass, "overdue_short") : loan.days === 0 ? t(hass, "today") : loan.days === 1 ? t(hass, "day_left") : t(hass, "days_left", { n: loan.days });
    const dueText = loan.due ? t(hass, overdue ? "overdue" : "due", { date: formatDate(hass, loan.due) }) : "";
    const meta = [loan.author, this._config.show_library !== false ? loan.library : null].filter(Boolean).join(" · ");

    // round icon buttons; the text is in the aria-label and the tooltip
    let action = "";
    if (loan.renewedToday) {
      const label = esc(t(hass, "renewed"));
      action = `<div class="act done" role="img" aria-label="${label}" title="${label}">${DONE_ICON}</div>`;
    } else if (loan.renewable && buttonId) {
      const pending = this._pending.has(loan.barcode);
      const failed = !pending && this._failed.has(loan.barcode);
      const label = esc(pending ? t(hass, "renewing") : failed ? t(hass, "failed") : t(hass, "renew_label", { title: loan.title }));
      const icon = pending ? `<span class="spin">${RENEW_ICON}</span>` : failed ? FAILED_ICON : RENEW_ICON;
      action = `<button type="button" class="act renew${failed ? " failed" : ""}" data-button="${esc(buttonId)}" data-barcode="${esc(loan.barcode)}"
                  aria-label="${label}" title="${label}" ${pending || failed ? "disabled" : ""}>${icon}</button>`;
    }

    const covers = this._config.show_covers !== false;
    return `<div class="row ${tone}${covers ? "" : " nocover"}">
      ${covers ? this._cover(loan) : ""}
      <svg class="ring" viewBox="0 0 56 56" role="img" aria-label="${esc(ringLabel)}">
        <circle class="track" cx="28" cy="28" r="${RING_RADIUS}"></circle>
        <circle class="bar${ring.full ? " full" : ""}" cx="28" cy="28" r="${RING_RADIUS}" stroke-dasharray="${ring.dash}" transform="rotate(-90 28 28)"></circle>
        <text x="28" y="34" text-anchor="middle">${esc(ringText)}</text>
      </svg>
      <div class="text">
        <div class="name">${esc(loan.title)}</div>
        ${meta ? `<div class="meta">${esc(meta)}</div>` : ""}
        ${dueText ? `<div class="due">${esc(dueText)}</div>` : ""}
      </div>
      ${action}
    </div>`;
  }

  /**
   * Cover stored by the integration (scaled into a fixed frame, top aligned) or a colored placeholder with the title.
   * Loaded right away (not lazy) and decoded off the main thread: in a pop-up, lazy images would only start
   * loading during its opening animation and make it stutter.
   */
  _cover(loan) {
    if (loan.cover_url && !this._brokenCovers.has(loan.cover_url)) {
      return `<div class="cover"><img src="${esc(loan.cover_url)}" alt="" decoding="async" data-cover="${esc(loan.cover_url)}"></div>`;
    }
    const color = PLACEHOLDER_COLORS[hashCode(loan.barcode || loan.title) % PLACEHOLDER_COLORS.length];
    return `<div class="cover"><div class="placeholder" style="--lib-cover:${color}" aria-hidden="true"><span>${esc(loan.title)}</span></div></div>`;
  }

  async _onClick(event) {
    const tab = event.target.closest("button[data-tab]");
    if (tab) {
      this._active = tab.dataset.tab;
      this._render();
      return;
    }
    const button = event.target.closest("button[data-button]");
    if (!button || button.disabled) return;
    const barcode = button.dataset.barcode;
    if (this._pending.has(barcode) || this._failed.has(barcode)) return; // one press at a time
    button.disabled = true; // at once, before the next render
    this._pending.add(barcode);
    this._render();
    try {
      await this._hass.callService("button", "press", { entity_id: button.dataset.button });
    } catch (e) {
      // Home Assistant shows the error message; the button stays locked for a few seconds
      this._failed.set(
        barcode,
        setTimeout(() => {
          this._failed.delete(barcode);
          this._render();
        }, FAILED_LOCK_MS)
      );
    } finally {
      this._pending.delete(barcode);
      this._render();
    }
  }
}

const CARD_STYLE = `
:host { display:block; }
ha-card.mode-light { color-scheme:light; --primary-text-color:#212121; --secondary-text-color:#5f6368; --divider-color:rgba(0,0,0,.12); --card-background-color:#fff; --ha-card-background:#fff; --ha-card-border-color:#e0e0e0; --lib-tile:#f4f6f8; }
ha-card.mode-dark { color-scheme:dark; --primary-text-color:#e1e1e1; --secondary-text-color:#a3a9b3; --divider-color:rgba(225,225,225,.12); --card-background-color:#1c1c1c; --ha-card-background:#1c1c1c; --ha-card-border-color:rgba(225,225,225,.12); --lib-tile:#262626; }
ha-card { display:block; box-sizing:border-box; margin:0 auto; padding:16px; color:var(--primary-text-color); container-type:inline-size; }
.head { display:flex; align-items:baseline; gap:8px; margin-bottom:12px; flex-wrap:wrap; }
.title { font-size:1.25em; font-weight:500; flex:1; min-width:0; }
.tabs { display:flex; gap:6px; flex:1 0 auto; flex-wrap:wrap; max-width:100%; }
.tab { font:inherit; font-size:.95em; min-height:36px; border:1px solid var(--divider-color, rgba(127,127,127,.3)); background:none; color:var(--primary-text-color); border-radius:18px; padding:6px 14px; cursor:pointer; }
.tab.active { background:var(--primary-color); border-color:var(--primary-color); color:var(--text-primary-color, #fff); }
.tab:focus-visible { outline:2px solid var(--primary-color); outline-offset:2px; }
.head { align-items:center; }
.valid { font-size:.85em; color:var(--secondary-text-color); margin-left:auto; text-align:right; }
.valid.warn { color:var(--warning-color, #ff9800); font-weight:500; }
.valid.alert, .valid.expired { color:var(--error-color, #db4437); font-weight:500; }
.banner { margin:0 0 10px; padding:10px 12px; border-radius:10px; font-size:.9em; font-weight:500;
          background:color-mix(in srgb, var(--error-color, #db4437) 16%, transparent); color:var(--error-color, #db4437); }
.tab { display:inline-flex; align-items:center; gap:6px; }
.dot { width:8px; height:8px; border-radius:4px; flex-shrink:0; background:var(--warning-color, #ff9800); }
.dot.alert, .dot.expired { background:var(--error-color, #db4437); }
.tab.active .dot { box-shadow:0 0 0 2px var(--text-primary-color, #fff); }
.list { display:flex; flex-direction:column; gap:8px; }
.row { display:flex; align-items:flex-start; gap:12px; padding:10px 12px; border-radius:12px; border:1px solid transparent;
       background:var(--lib-tile, color-mix(in srgb, var(--primary-text-color) 5%, var(--card-background-color, var(--ha-card-background, #fff)))); }
.row.overdue { border-color:var(--error-color, #db4437); }
/* cover: fixed frame, image scaled in without cropping and aligned to the top */
.cover { width:84px; height:124px; flex-shrink:0; display:flex; align-items:flex-start; justify-content:center; }
.cover img { display:block; max-width:100%; max-height:100%; border-radius:6px; box-shadow:0 2px 8px rgba(0,0,0,.45); }
.placeholder { box-sizing:border-box; width:100%; height:100%; border-radius:6px; padding:8px; display:flex; align-items:flex-end;
               background:linear-gradient(160deg, var(--lib-cover) 0%, rgba(0,0,0,.6) 150%); box-shadow:0 2px 8px rgba(0,0,0,.45); color:#fff; }
.placeholder span { font-size:11px; font-weight:700; line-height:1.15; hyphens:auto; -webkit-hyphens:auto; overflow-wrap:break-word;
                    display:-webkit-box; -webkit-line-clamp:3; -webkit-box-orient:vertical; overflow:hidden; }
.ring { width:44px; height:44px; flex-shrink:0; }
.ring .track { fill:none; stroke:color-mix(in srgb, var(--primary-text-color) 14%, transparent); stroke-width:6; }
.ring .bar { fill:none; stroke:var(--lib-tone); stroke-width:6; stroke-linecap:round; }
.ring .bar.full { stroke-linecap:butt; }
.ring text { font-size:18px; font-weight:700; fill:var(--lib-tone); font-family:inherit; }
.row { --lib-tone:var(--secondary-text-color); }
.row.soon { --lib-tone:var(--warning-color, #ff9800); }
.row.overdue { --lib-tone:var(--error-color, #db4437); }
.text { flex:1; min-width:0; display:flex; flex-direction:column; gap:3px; padding-top:2px; }
.name { font-size:1.08em; font-weight:500; line-height:1.3; display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; overflow:hidden; }
.meta { font-size:.8em; color:var(--secondary-text-color); line-height:1.35; overflow:hidden;
        display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; }
.due { font-size:.85em; font-weight:500; color:var(--lib-tone); }
.row.normal .due { color:var(--secondary-text-color); }
/* round action buttons, vertically centered */
.act { align-self:center; box-sizing:border-box; flex-shrink:0; width:50px; height:50px; padding:0; border:0; border-radius:25px;
       display:flex; align-items:center; justify-content:center; }
.act svg { width:21px; height:21px; }
.act.renew { background:color-mix(in srgb, var(--primary-color) 18%, transparent); color:var(--primary-color); cursor:pointer; }
.act.renew:hover { background:color-mix(in srgb, var(--primary-color) 26%, transparent); }
.act.renew:focus-visible { outline:2px solid var(--primary-color); outline-offset:2px; }
.act.renew[disabled] { cursor:default; opacity:.7; }
.act.renew.failed { background:color-mix(in srgb, var(--error-color, #db4437) 18%, transparent); color:var(--error-color, #db4437); opacity:1; }
.act.done { background:color-mix(in srgb, var(--success-color, #43a047) 18%, transparent); color:var(--success-color, #43a047); }
.message { padding:8px 4px; color:var(--secondary-text-color); }
.spin { display:flex; animation:lib-spin 1s linear infinite; }
@keyframes lib-spin { to { transform:rotate(360deg); } }
/* without covers: larger ring, everything centered like before */
.row.nocover { align-items:center; }
.row.nocover .ring { width:56px; height:56px; }
.row.nocover .text { padding-top:0; }
/* narrow columns: smaller cover, ring and buttons */
@container (max-width: 400px) {
  .row { gap:10px; padding:10px; }
  .cover { width:60px; height:88px; }
  .placeholder { padding:6px; }
  .placeholder span { font-size:9px; }
  .ring { width:36px; height:36px; }
  .meta { -webkit-line-clamp:1; }
  .act { width:44px; height:44px; }
}
`;

/* =====================================================================
 * Visual editor (Home Assistant form, keeps all other options such as grid_options)
 * ===================================================================== */

class MuenchnerStadtbibliothekCardEditor extends HTMLElement {
  setConfig(config) {
    this._config = { ...(config || {}) };
    this._render();
  }

  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    if (first || !this._form) this._render();
    else this._form.hass = hass;
  }

  _schema() {
    const hass = this._hass;
    const accounts = findAccounts(hass);
    const fields = [
      {
        name: "account",
        selector: {
          select: {
            mode: "dropdown",
            options: [{ value: ALL, label: t(hass, "editor_all") }, ...accounts.map((a) => ({ value: a.name, label: a.name }))],
          },
        },
      },
    ];
    // The title is only shown for a single account; with several accounts the pills are the heading
    if (this._config.account || accounts.length <= 1) fields.push({ name: "title", selector: { text: {} } });
    fields.push(
      {
        type: "grid",
        name: "",
        schema: [
          { name: "loan_days", selector: { number: { min: 7, max: 60, step: 1, mode: "box", unit_of_measurement: "d" } } },
          { name: "max_width", selector: { number: { min: 0, max: 2000, step: 10, mode: "box", unit_of_measurement: "px" } } },
          { name: "card_warn_days", selector: { number: { min: 0, max: 120, step: 1, mode: "box", unit_of_measurement: "d" } } },
          {
            name: "appearance",
            selector: { select: { mode: "dropdown", options: APPEARANCES.map((value) => ({ value, label: t(hass, `appearance_${value}`) })) } },
          },
        ],
      },
      { name: "show_card", selector: { boolean: {} } },
      { name: "show_library", selector: { boolean: {} } },
      { name: "show_covers", selector: { boolean: {} } }
    );
    return fields;
  }

  _accountValue() {
    const wanted = this._config.account;
    if (!wanted) return ALL;
    return findAccounts(this._hass).find((a) => matchAccount(a, wanted))?.name || wanted;
  }

  _render() {
    if (!this._hass || !this._config) return;
    if (!this._form) {
      this._form = document.createElement("ha-form");
      this._form.computeLabel = (field) => t(this._hass, `editor_${field.name}`);
      this._form.addEventListener("value-changed", (e) => this._changed(e.detail.value));
      this.appendChild(this._form);
    }
    this._form.hass = this._hass;
    this._form.schema = this._schema();
    this._form.data = {
      account: this._accountValue(),
      title: this._config.title ?? "",
      loan_days: this._config.loan_days ?? DEFAULT_LOAN_DAYS,
      max_width: this._config.max_width ?? DEFAULT_MAX_WIDTH,
      card_warn_days: this._config.card_warn_days ?? DEFAULT_CARD_WARN_DAYS,
      appearance: this._config.appearance || "auto",
      show_card: this._config.show_card !== false,
      show_library: this._config.show_library !== false,
      show_covers: this._config.show_covers !== false,
    };
  }

  /** Only options that differ from the defaults are stored; unknown options (grid_options, ...) are kept. */
  _changed(value) {
    const config = { ...this._config, type: this._config.type || `custom:${CARD_TYPE}` };
    if (value.account && value.account !== ALL) config.account = value.account;
    else delete config.account;
    if (value.title) config.title = value.title;
    else delete config.title;
    if (value.loan_days && Number(value.loan_days) !== DEFAULT_LOAN_DAYS) config.loan_days = Number(value.loan_days);
    else delete config.loan_days;
    if (value.max_width !== undefined && value.max_width !== "" && Number(value.max_width) !== DEFAULT_MAX_WIDTH) config.max_width = Number(value.max_width);
    else delete config.max_width;
    if (value.card_warn_days !== undefined && value.card_warn_days !== "" && Number(value.card_warn_days) !== DEFAULT_CARD_WARN_DAYS)
      config.card_warn_days = Number(value.card_warn_days);
    else delete config.card_warn_days;
    if (value.appearance && value.appearance !== "auto") config.appearance = value.appearance;
    else delete config.appearance;
    if (value.show_card === false) config.show_card = false;
    else delete config.show_card;
    if (value.show_library === false) config.show_library = false;
    else delete config.show_library;
    if (value.show_covers === false) config.show_covers = false;
    else delete config.show_covers;
    this._config = config;
    this._form.schema = this._schema(); // title field appears or disappears with the account choice
    this.dispatchEvent(new CustomEvent("config-changed", { detail: { config }, bubbles: true, composed: true }));
  }
}

/* =====================================================================
 * Registration
 * ===================================================================== */

if (!customElements.get(`${CARD_TYPE}-editor`)) customElements.define(`${CARD_TYPE}-editor`, MuenchnerStadtbibliothekCardEditor);
if (!customElements.get(CARD_TYPE)) {
  customElements.define(CARD_TYPE, MuenchnerStadtbibliothekCard);
  window.customCards = window.customCards || [];
  window.customCards.push({
    type: CARD_TYPE,
    name: "Münchner Stadtbibliothek",
    description: "Current loans with remaining days and renewal",
    preview: true,
  });
  console.info("%c MUENCHNER-STADTBIBLIOTHEK-CARD %c " + VERSION + " ", "background:#1c5c8c;color:#fff", "");
}
