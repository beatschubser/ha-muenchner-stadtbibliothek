/*
 * Münchner Stadtbibliothek card: current loans with remaining days and renewal.
 * Served by the integration (no build step, no external libraries).
 *
 * Card options (all optional, editable in the visual editor):
 *   account     name of one library card (as set up in the integration); default: all cards as pills
 *   title       heading when only one card is shown (default: its name)
 *   show_card   show "card valid until" in the header (default: true)
 *   loan_days   loan period in days, full ring (default: 28)
 *   appearance  auto | light | dark (default: auto = theme)
 */

const VERSION = "0.3.0";
const DOMAIN = "muenchner_stadtbibliothek";
const CARD_TYPE = "muenchner-stadtbibliothek-card";
const DEFAULT_LOAN_DAYS = 28;
const SOON_DAYS = 3; // remaining days shown in the warning color
const APPEARANCES = ["auto", "light", "dark"];
const ALL = "__all__"; // editor value for "all accounts as pills"

const TEXTS = {
  de: {
    card_valid: "Ausweis bis {date}",
    due: "fällig {date}",
    overdue: "überfällig seit {date}",
    days_left: "noch {n} Tage",
    day_left: "noch 1 Tag",
    today: "heute fällig",
    overdue_short: "überfällig",
    renew: "Verlängern",
    renew_label: "{title} verlängern",
    renewing: "Verlängere …",
    renewed: "Heute verlängert",
    empty: "Keine Ausleihen",
    unavailable: "Keine Daten",
    no_entity: "Kein Ausweis der Integration Münchner Stadtbibliothek gefunden.",
    account_not_found: "Ausweis „{name}“ nicht gefunden.",
    editor_account: "Ausweis",
    editor_all: "Alle (als Auswahl-Pillen)",
    editor_title: "Titel (leer = Name des Ausweises)",
    editor_show_card: "Ausweis-Gültigkeit anzeigen",
    editor_loan_days: "Leihfrist (Tage, voller Ring)",
    editor_appearance: "Darstellung",
    appearance_auto: "Wie Theme",
    appearance_light: "Hell",
    appearance_dark: "Dunkel",
  },
  en: {
    card_valid: "Card valid until {date}",
    due: "due {date}",
    overdue: "overdue since {date}",
    days_left: "{n} days left",
    day_left: "1 day left",
    today: "due today",
    overdue_short: "overdue",
    renew: "Renew",
    renew_label: "Renew {title}",
    renewing: "Renewing …",
    renewed: "Renewed today",
    empty: "No loans",
    unavailable: "No data",
    no_entity: "No library card of the Münchner Stadtbibliothek integration found.",
    account_not_found: "Library card \"{name}\" not found.",
    editor_account: "Library card",
    editor_all: "All (as selection pills)",
    editor_title: "Title (empty = name of the card)",
    editor_show_card: "Show card validity",
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
const RING_RADIUS = 23;
const RING_LENGTH = 2 * Math.PI * RING_RADIUS;

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

  /** Accounts this card shows: one fixed account (option account, or entity of 0.2.0) or all. */
  _accounts() {
    const all = findAccounts(this._hass);
    const wanted = this._config.account || this._config.entity;
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
        const renewedToday = loan.renewed_today ?? String(loan.hint || "").startsWith("Heute verlängert");
        return { ...loan, due, days, renewedToday, period };
      })
      .sort((a, b) => (a.days ?? 9999) - (b.days ?? 9999) || String(a.title).localeCompare(String(b.title)));
  }

  _render() {
    if (!this._hass) return;
    const hass = this._hass;
    const appearance = APPEARANCES.includes(this._config.appearance) ? this._config.appearance : "auto";
    this._card.className = appearance === "auto" ? "" : `mode-${appearance}`;

    const accounts = this._accounts();
    if (!accounts.length) {
      this._size = 2;
      const wanted = this._config.account || this._config.entity;
      this._card.innerHTML = `<div class="message">${esc(wanted ? t(hass, "account_not_found", { name: wanted }) : t(hass, "no_entity"))}</div>`;
      return;
    }
    const account = accounts.find((a) => a.id === this._active) || accounts[0];
    this._active = account.id;

    const validity = account.validity ? hass.states[account.validity] : null;
    const validDate = validity && parseDate(validity.state);
    const valid =
      this._config.show_card !== false && validDate
        ? `<div class="valid">${esc(t(hass, "card_valid", { date: formatDate(hass, validDate, true) }))}</div>`
        : "";
    let head;
    if (accounts.length > 1) {
      const pills = accounts
        .map(
          (a) =>
            `<button type="button" class="tab ${a.id === account.id ? "active" : ""}" data-tab="${esc(a.id)}" aria-pressed="${a.id === account.id}">${esc(a.name)}</button>`
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
    this._card.innerHTML = head + body;
  }

  _row(loan, buttonId) {
    const hass = this._hass;
    const overdue = loan.days !== null && loan.days < 0;
    const tone = overdue ? "overdue" : loan.days !== null && loan.days <= SOON_DAYS ? "soon" : "normal";
    const share = overdue ? 1 : Math.max(0.04, Math.min(1, (loan.days ?? 0) / loan.period));
    const ringText = overdue ? "!" : loan.days ?? "?";
    const ringLabel =
      loan.days === null ? "" : overdue ? t(hass, "overdue_short") : loan.days === 0 ? t(hass, "today") : loan.days === 1 ? t(hass, "day_left") : t(hass, "days_left", { n: loan.days });
    const dueText = loan.due ? t(hass, overdue ? "overdue" : "due", { date: formatDate(hass, loan.due) }) : "";
    const meta = [loan.author, loan.library].filter(Boolean).join(" · ");

    let action = "";
    if (loan.renewedToday) {
      action = `<div class="pill done" role="img" aria-label="${esc(t(hass, "renewed"))}">${DONE_ICON}<span class="label">${esc(t(hass, "renewed"))}</span></div>`;
    } else if (loan.renewable && buttonId) {
      const pending = this._pending.has(loan.barcode);
      action = `<button type="button" class="pill renew" data-button="${esc(buttonId)}" data-barcode="${esc(loan.barcode)}"
                  aria-label="${esc(t(hass, "renew_label", { title: loan.title }))}" ${pending ? "disabled" : ""}>
                  ${pending ? `<span class="spin">${RENEW_ICON}</span><span class="label">${esc(t(hass, "renewing"))}</span>` : `${RENEW_ICON}<span class="label">${esc(t(hass, "renew"))}</span>`}
                </button>`;
    }

    return `<div class="row ${tone}">
      <svg class="ring" viewBox="0 0 56 56" role="img" aria-label="${esc(ringLabel)}">
        <circle class="track" cx="28" cy="28" r="${RING_RADIUS}"></circle>
        <circle class="bar" cx="28" cy="28" r="${RING_RADIUS}" stroke-dasharray="${(share * RING_LENGTH).toFixed(1)} ${RING_LENGTH.toFixed(1)}" transform="rotate(-90 28 28)"></circle>
        <text x="28" y="33" text-anchor="middle">${esc(ringText)}</text>
      </svg>
      <div class="text">
        <div class="name">${esc(loan.title)}</div>
        ${meta ? `<div class="meta">${esc(meta)}</div>` : ""}
        ${dueText ? `<div class="due">${esc(dueText)}</div>` : ""}
      </div>
      ${action}
    </div>`;
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
    this._pending.add(barcode);
    this._render();
    try {
      await this._hass.callService("button", "press", { entity_id: button.dataset.button });
    } catch (e) {
      // Home Assistant shows the error message itself
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
ha-card { display:block; padding:16px; color:var(--primary-text-color); container-type:inline-size; }
.head { display:flex; align-items:baseline; gap:8px; margin-bottom:12px; flex-wrap:wrap; }
.title { font-size:1.25em; font-weight:500; flex:1; min-width:0; }
.tabs { display:flex; gap:6px; flex:1; flex-wrap:wrap; min-width:0; }
.tab { font:inherit; font-size:.95em; min-height:36px; border:1px solid var(--divider-color, rgba(127,127,127,.3)); background:none; color:var(--primary-text-color); border-radius:18px; padding:6px 14px; cursor:pointer; }
.tab.active { background:var(--primary-color); border-color:var(--primary-color); color:var(--text-primary-color, #fff); }
.tab:focus-visible { outline:2px solid var(--primary-color); outline-offset:2px; }
.head { align-items:center; }
.valid { font-size:.85em; color:var(--secondary-text-color); }
.list { display:flex; flex-direction:column; gap:8px; }
.row { display:flex; align-items:center; gap:14px; padding:12px; border-radius:12px; border:1px solid transparent;
       background:var(--lib-tile, color-mix(in srgb, var(--primary-text-color) 5%, var(--card-background-color, var(--ha-card-background, #fff)))); }
.row.overdue { border-color:var(--error-color, #db4437); }
.ring { width:56px; height:56px; flex-shrink:0; }
.ring .track { fill:none; stroke:color-mix(in srgb, var(--primary-text-color) 14%, transparent); stroke-width:6; }
.ring .bar { fill:none; stroke:var(--lib-tone); stroke-width:6; stroke-linecap:round; }
.ring text { font-size:16px; font-weight:700; fill:var(--lib-tone); font-family:inherit; }
.row { --lib-tone:var(--secondary-text-color); }
.row.soon { --lib-tone:var(--warning-color, #ff9800); }
.row.overdue { --lib-tone:var(--error-color, #db4437); }
.text { flex:1; min-width:0; display:flex; flex-direction:column; gap:3px; }
.name { font-size:1em; font-weight:500; line-height:1.3; display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; overflow:hidden; }
.meta { font-size:.8em; color:var(--secondary-text-color); white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.due { font-size:.85em; font-weight:500; color:var(--lib-tone); }
.row.normal .due { color:var(--secondary-text-color); }
.pill { box-sizing:border-box; flex-shrink:0; width:140px; min-height:44px; padding:0 12px; border:0; border-radius:22px;
        display:flex; align-items:center; justify-content:center; gap:6px; font:inherit; font-size:.85em; font-weight:500; text-align:center; }
.pill.renew { background:color-mix(in srgb, var(--primary-color) 18%, transparent); color:var(--primary-color); cursor:pointer; }
.pill.renew:hover { background:color-mix(in srgb, var(--primary-color) 26%, transparent); }
.pill.renew:focus-visible { outline:2px solid var(--primary-color); outline-offset:2px; }
.pill.renew[disabled] { cursor:default; opacity:.7; }
.pill.done { background:color-mix(in srgb, var(--success-color, #43a047) 18%, transparent); color:var(--success-color, #43a047); }
.pill.done svg { display:none; }
.message { padding:8px 4px; color:var(--secondary-text-color); }
.spin { display:flex; animation:lib-spin 1s linear infinite; }
@keyframes lib-spin { to { transform:rotate(360deg); } }
/* narrow columns: icon-only buttons, the label stays available to screen readers via aria-label */
@container (max-width: 400px) {
  .row { gap:10px; padding:10px; }
  .pill { width:44px; padding:0; }
  .pill .label { display:none; }
  .pill.done svg { display:block; }
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
    if (this._config.account || this._config.entity || accounts.length <= 1) fields.push({ name: "title", selector: { text: {} } });
    fields.push(
      {
        type: "grid",
        name: "",
        schema: [
          { name: "loan_days", selector: { number: { min: 7, max: 60, step: 1, mode: "box", unit_of_measurement: "d" } } },
          {
            name: "appearance",
            selector: { select: { mode: "dropdown", options: APPEARANCES.map((value) => ({ value, label: t(hass, `appearance_${value}`) })) } },
          },
        ],
      },
      { name: "show_card", selector: { boolean: {} } }
    );
    return fields;
  }

  _accountValue() {
    const wanted = this._config.account || this._config.entity;
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
      appearance: this._config.appearance || "auto",
      show_card: this._config.show_card !== false,
    };
  }

  /** Only options that differ from the defaults are stored; unknown options (grid_options, ...) are kept. */
  _changed(value) {
    const config = { ...this._config, type: this._config.type || `custom:${CARD_TYPE}` };
    delete config.entity; // replaced by account (name)
    if (value.account && value.account !== ALL) config.account = value.account;
    else delete config.account;
    if (value.title) config.title = value.title;
    else delete config.title;
    if (value.loan_days && Number(value.loan_days) !== DEFAULT_LOAN_DAYS) config.loan_days = Number(value.loan_days);
    else delete config.loan_days;
    if (value.appearance && value.appearance !== "auto") config.appearance = value.appearance;
    else delete config.appearance;
    if (value.show_card === false) config.show_card = false;
    else delete config.show_card;
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
