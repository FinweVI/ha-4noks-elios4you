/**
 * Elios4You Scheduler Card — Phase 3 (editable grid)
 *
 * Displays the Power Reducer 7-day × 48-slot schedule stored on the device.
 * Click a slot to cycle its mode (off → auto → boost → off).
 * Click and drag across slots to paint them all with the same mode.
 * A Save / Discard action bar appears whenever unsaved changes are pending.
 * Reads via get_schedule, writes via set_schedule (SupportsResponse.ONLY / plain call).
 * Detects backend version mismatches and offers a one-click cache-clear reload.
 *
 * CARD_VERSION must be kept in sync with VERSION in const.py.
 */

// ─── Constants ───────────────────────────────────────────────────────────────

const CARD_VERSION = '1.2.0'; // Keep in sync with custom_components/4noks_elios4you/const.py
const DOMAIN = '4noks_elios4you';
// Day labels and device-day mapping are computed at init from hass.locale.first_weekday.
// Device uses US ordering: 0=Sun, 1=Mon, …, 6=Sat.
const _DAYS = ['sun', 'mon', 'tue', 'wed', 'thu', 'fri', 'sat'];
const _DAY_LABELS = { sun: 'Sun', mon: 'Mon', tue: 'Tue', wed: 'Wed', thu: 'Thu', fri: 'Fri', sat: 'Sat' };
const _DEVICE_IDX  = { sun: 0, mon: 1, tue: 2, wed: 3, thu: 4, fri: 5, sat: 6 };
const SLOT_COUNT = 48;

/** Cycle order when clicking a slot. */
const NEXT_MODE = { off: 'auto', auto: 'boost', boost: 'off' };

/** Display metadata for each mode value returned by get_schedule. */
const MODES = {
  off:   { label: 'Off',   color: 'var(--elios-off-color,   #bdbdbd)' },
  auto:  { label: 'Auto',  color: 'var(--elios-auto-color,  #4caf50)' },
  boost: { label: 'Boost', color: 'var(--elios-boost-color, #ff9800)' },
};

// ─── Helpers ─────────────────────────────────────────────────────────────────

/**
 * HTML-escape a value before interpolating into innerHTML.
 * Covers all five dangerous characters: & < > " '
 */
function escapeHtml(value) {
  return String(value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

/** Convert 0-based 30-min slot index to 'HH:MM' display string. */
function slotToTime(slot) {
  const mins = slot * 30;
  return `${String(Math.floor(mins / 60)).padStart(2, '0')}:${String(mins % 60).padStart(2, '0')}`;
}

// ─── Card ────────────────────────────────────────────────────────────────────

class Elios4YouSchedulerCard extends HTMLElement {

  // ── Lifecycle ──────────────────────────────────────────────────────────────

  constructor() {
    super();
    this.attachShadow({ mode: 'open' });

    /** @type {import('../node_modules/home-assistant-js-websocket').HomeAssistant|null} */
    this._hass = null;
    /** @type {{config_entry_id: string, title?: string}|null} */
    this._config = null;

    /** 7-element array, each a 48-element array of mode strings ('off'|'auto'|'boost'). */
    this._schedule = null;
    this._loading = false;
    this._error = null;

    /** Non-null when the backend version differs from CARD_VERSION. */
    this._versionMismatch = null; // { serverVersion: string }

    this._initialized = false;

    // ── Locale-aware day ordering ───────────────────────────────────────────
    /** Display labels ordered by locale first-weekday (e.g. ['Mon',…,'Sun']). */
    this._dayNames = [];
    /** Maps display row index → device day index (device: 0=Sun…6=Sat). */
    this._displayToDevice = [];

    // ── Phase 3: editing state ──────────────────────────────────────────────

    /**
     * Unsaved modifications keyed by day index.
     * Each value is a full 48-element slots array reflecting the intended state.
     * @type {Map<number, string[]>}
     */
    this._pending = new Map();

    /** True while the set_schedule calls are in flight. */
    this._saving = false;

    /** Non-null when save failed. */
    this._saveError = null;

    /** True from mousedown to mouseup (drag in progress). */
    this._dragActive = false;

    /** Mode being painted during current drag. */
    this._dragMode = null;

    /** Day row being dragged on (drag restricted to a single day row). */
    this._dragDay = null;

    /** Bound document-level handlers (kept for cleanup). */
    this._boundDocMousemove = null;
    this._boundDocMouseup = null;
  }

  connectedCallback() {
    // Re-check version whenever card enters DOM (covers navigation back to dashboard)
    if (this._hass) {
      this._checkVersion();
    }
  }

  // ── HA interface ───────────────────────────────────────────────────────────

  set hass(hass) {
    this._hass = hass;
    if (!this._initialized && this._config) {
      this._initialized = true;
      this._init();
    }
  }

  setConfig(config) {
    if (!config || !config.config_entry_id) {
      throw new Error('elios4you-scheduler-card: config_entry_id is required.');
    }
    // Optional: first_weekday override ('monday'|'sunday'|'saturday') — overrides HA locale.
    // Use this if the card's day order doesn't match your 4noks app display.
    const validFirstWeekdays = ['monday', 'sunday', 'saturday'];
    if (config.first_weekday && !validFirstWeekdays.includes(config.first_weekday)) {
      throw new Error(`elios4you-scheduler-card: invalid first_weekday '${config.first_weekday}'. Use: monday, sunday, saturday.`);
    }
    const prevFirstWeekday = this._config?.first_weekday;
    this._config = config;
    // If hass is already set when config arrives, initialize now
    if (this._hass && !this._initialized) {
      this._initialized = true;
      this._init();
    } else if (this._initialized && config.first_weekday !== prevFirstWeekday) {
      // first_weekday changed — recompute mapping and reload schedule
      this._computeDayMapping();
      this._loadSchedule();
    }
  }

  /** Tells HA dashboard how many grid rows this card occupies. */
  getCardSize() { return 6; }

  /**
   * Auto-populate the card config when added via the UI card picker.
   * Queries HA for the first config entry matching this integration's domain.
   */
  static async getStubConfig(hass) {
    try {
      const entries = await hass.connection.sendMessagePromise({
        type: 'config_entries/get',
        domain: DOMAIN,
      });
      if (entries && entries.length > 0) {
        return { config_entry_id: entries[0].entry_id };
      }
    } catch (_) {
      // WebSocket command unavailable or no entries — fall through to empty config
    }
    return { config_entry_id: '' };
  }

  // ── Initialisation ─────────────────────────────────────────────────────────

  /**
   * Build day labels and display→device index map.
   *
   * Priority order:
   *   1. card config `first_weekday` (explicit override by user)
   *   2. `hass.locale.first_weekday` (HA profile setting)
   *   3. 'monday' (fallback)
   *
   * Device uses US week: 0=Sun, 1=Mon, …, 6=Sat.
   * If the card's day order doesn't match your 4noks app, set `first_weekday`
   * explicitly in the card YAML (e.g. `first_weekday: sunday`).
   */
  _computeDayMapping() {
    // Config override takes precedence over locale
    const firstWeekday = this._config?.first_weekday
      || this._hass?.locale?.first_weekday
      || 'monday';
    const startKey = firstWeekday.slice(0, 3).toLowerCase();
    let startIdx = _DAYS.indexOf(startKey);
    if (startIdx === -1) startIdx = 1; // fallback: Monday

    this._dayNames        = Array.from({ length: 7 }, (_, i) => _DAY_LABELS[_DAYS[(startIdx + i) % 7]]);
    this._displayToDevice = Array.from({ length: 7 }, (_, i) => _DEVICE_IDX[_DAYS[(startIdx + i) % 7]]);

    // Debug: log resolved day mapping so mismatches can be spotted in browser console
    console.debug(
      '[elios4you-scheduler] day mapping:',
      `first_weekday source: ${this._config?.first_weekday ? 'config override' : 'locale/fallback'}`,
      `resolved: "${firstWeekday}"`,
      `order: ${this._dayNames.join(' → ')}`,
      `deviceDays: [${this._displayToDevice.join(',')}]`,
    );
  }

  async _init() {
    this._computeDayMapping();
    // Run version check and schedule load in parallel; both update the UI independently.
    this._checkVersion();
    await this._loadSchedule();
  }

  // ── Version check ──────────────────────────────────────────────────────────

  async _checkVersion() {
    if (!this._hass) return;
    try {
      const result = await this._hass.connection.sendMessagePromise({
        type: `${DOMAIN}/lovelace_version`,
      });
      if (result && result.version && result.version !== CARD_VERSION) {
        this._versionMismatch = { serverVersion: result.version };
        this._render();
      } else {
        // Versions match — clear any stale banner
        if (this._versionMismatch !== null) {
          this._versionMismatch = null;
          this._render();
        }
      }
    } catch (_) {
      // WebSocket command unavailable (e.g. older backend) — silent, don't break the card
    }
  }

  async _clearCacheAndReload() {
    try {
      if ('caches' in window) {
        const names = await caches.keys();
        await Promise.all(names.map(n => caches.delete(n)));
      }
    } catch (_) {
      // Cache API unavailable (e.g. non-HTTPS) — reload anyway
    }
    location.reload(true);
  }

  // ── Data loading ───────────────────────────────────────────────────────────

  async _loadSchedule() {
    if (!this._hass || !this._config) return;
    // Discard any unsaved edits when explicitly reloading from device
    this._pending.clear();
    this._saveError = null;
    this._loading = true;
    this._error = null;
    this._render();

    // Fetch all 7 days in parallel. Each day retries individually on failure so
    // only the failing call is repeated, not the whole batch.
    // This handles transient failures (device briefly busy, lock contention on page load).
    const MAX_RETRIES = 3;
    const RETRY_DELAY_MS = 1500;

    try {
      // Display rows are in ISO order (Mon=0…Sun=6); device uses US ordering (Sun=0…Sat=6).
      // DISPLAY_TO_DEVICE maps each display row to the correct device day index.
      this._schedule = await Promise.all(
        Array.from({ length: 7 }, async (_, displayRow) => {
          const deviceDay = this._displayToDevice[displayRow];
          let lastError;
          for (let attempt = 0; attempt <= MAX_RETRIES; attempt++) {
            if (attempt > 0) {
              await new Promise(resolve => setTimeout(resolve, RETRY_DELAY_MS));
              if (!this._hass || !this._config) throw lastError; // card torn down
              console.warn(`[elios4you-scheduler] Retrying day ${deviceDay} (attempt ${attempt + 1})…`);
            }
            try {
              const result = await this._hass.connection.sendMessagePromise({
                type: 'call_service',
                domain: DOMAIN,
                service: 'get_schedule',
                service_data: { config_entry_id: this._config.config_entry_id, day: deviceDay },
                return_response: true,
              });
              // result.response: { day: string, slots: [{time: string, mode: string}] }
              return result.response.slots.map(s => s.mode);
            } catch (err) {
              lastError = err;
              if (attempt < MAX_RETRIES) {
                console.warn(`[elios4you-scheduler] Day ${deviceDay} load attempt ${attempt + 1} failed:`, err.message || err);
              }
            }
          }
          throw lastError;
        })
      );
    } catch (err) {
      this._error = err.message || 'Failed to load schedule from device.';
    } finally {
      this._loading = false;
      this._render();
    }
  }

  // ── Editing ────────────────────────────────────────────────────────────────

  /** Returns the current (possibly pending-modified) slots array for a day. */
  _getEffectiveSlots(day) {
    return this._pending.get(day) ?? this._schedule[day];
  }

  /**
   * Apply the current drag mode to a single slot, updating both the pending
   * state map and the live DOM element (no full re-render during drag).
   */
  _applyPaint(day, slot) {
    if (!this._pending.has(day)) {
      // Copy the committed schedule for this day before modifying
      this._pending.set(day, [...this._schedule[day]]);
    }
    const slots = this._pending.get(day);
    if (slots[slot] === this._dragMode) return; // already correct — skip DOM update
    slots[slot] = this._dragMode;

    // Direct DOM update for responsiveness (avoid full re-render during drag)
    const el = this.shadowRoot.querySelector(`[data-day="${day}"][data-slot="${slot}"]`);
    if (el) {
      const info = MODES[this._dragMode] || MODES.off;
      el.style.background = info.color;
      el.title = `${slotToTime(slot)} – ${info.label}`;
    }
  }

  _handleSlotMousedown(e) {
    if (e.button !== 0) return; // left button only
    // composedPath() resolves the actual element inside shadow DOM
    const target = e.composedPath ? e.composedPath()[0] : e.target;
    if (!target || !target.classList.contains('slot')) return;

    const day  = parseInt(target.dataset.day,  10);
    const slot = parseInt(target.dataset.slot, 10);
    if (isNaN(day) || isNaN(slot)) return;

    const currentMode = this._getEffectiveSlots(day)[slot];
    this._dragMode   = NEXT_MODE[currentMode] || 'off';
    this._dragDay    = day;   // drag is restricted to this day row
    this._dragActive = true;

    this._applyPaint(day, slot);

    // Register document-level listeners (cleaned up in mouseup)
    this._boundDocMousemove = this._handleDocMousemove.bind(this);
    this._boundDocMouseup   = this._handleDocMouseup.bind(this);
    document.addEventListener('mousemove', this._boundDocMousemove);
    document.addEventListener('mouseup',   this._boundDocMouseup);

    e.preventDefault(); // prevent text selection while dragging
  }

  _handleDocMousemove(e) {
    if (!this._dragActive) return;
    const target = e.composedPath ? e.composedPath()[0] : e.target;
    if (!target || !target.classList.contains('slot')) return;

    const day  = parseInt(target.dataset.day,  10);
    const slot = parseInt(target.dataset.slot, 10);
    if (isNaN(day) || isNaN(slot)) return;

    // Restrict drag to the day row where the drag started
    if (day !== this._dragDay) return;

    this._applyPaint(day, slot);
  }

  _handleDocMouseup() {
    this._dragActive = false;

    if (this._boundDocMousemove) {
      document.removeEventListener('mousemove', this._boundDocMousemove);
      this._boundDocMousemove = null;
    }
    if (this._boundDocMouseup) {
      document.removeEventListener('mouseup', this._boundDocMouseup);
      this._boundDocMouseup = null;
    }

    // Full re-render to update action bar visibility and day-label asterisks
    this._render();
  }

  async _saveSchedule() {
    this._saving    = true;
    this._saveError = null;
    this._render();

    try {
      // Save each modified day sequentially to avoid flooding the device.
      // _pending is keyed by display row; translate to device day via DISPLAY_TO_DEVICE.
      for (const [displayRow, slots] of this._pending) {
        const deviceDay = this._displayToDevice[displayRow];
        await this._hass.connection.sendMessagePromise({
          type: 'call_service',
          domain: DOMAIN,
          service: 'set_schedule',
          service_data: {
            config_entry_id: this._config.config_entry_id,
            day: deviceDay,
            slots,
          },
        });
        // Commit this display row's pending state into the reference schedule
        this._schedule[displayRow] = [...slots];
      }
      this._pending.clear();
    } catch (err) {
      this._saveError = err.message || 'Failed to save schedule.';
    } finally {
      this._saving = false;
      this._render();
    }
  }

  _discardPending() {
    this._pending.clear();
    this._saveError = null;
    this._render();
  }

  // ── Rendering ──────────────────────────────────────────────────────────────

  _render() {
    if (!this.shadowRoot) return;
    const title      = (this._config && this._config.title) || 'Power Reducer Schedule';
    const hasPending = this._pending.size > 0;

    this.shadowRoot.innerHTML = `
      <style>${this._styles()}</style>
      <ha-card>
        <div class="card-content">
          ${this._renderHeader(title)}
          ${this._versionMismatch ? this._renderVersionBanner()         : ''}
          ${this._saveError       ? this._renderSaveError()             : ''}
          ${(hasPending || this._saving) ? this._renderActionBar()      : ''}
          ${this._loading         ? this._renderLoading()               : ''}
          ${this._error           ? this._renderError(this._error)      : ''}
          ${(!this._loading && !this._error && this._schedule)
            ? this._renderGrid()   : ''}
          ${(!this._loading && !this._error && this._schedule)
            ? this._renderLegend() : ''}
        </div>
      </ha-card>
    `;

    // ── Button event listeners ──────────────────────────────────────────────
    const refreshBtn = this.shadowRoot.getElementById('refresh-btn');
    if (refreshBtn) refreshBtn.addEventListener('click', () => this._loadSchedule());

    const retryBtn = this.shadowRoot.getElementById('retry-btn');
    if (retryBtn) retryBtn.addEventListener('click', () => this._loadSchedule());

    const reloadBtn = this.shadowRoot.getElementById('reload-btn');
    if (reloadBtn) reloadBtn.addEventListener('click', () => this._clearCacheAndReload());

    const saveBtn = this.shadowRoot.getElementById('save-btn');
    if (saveBtn) saveBtn.addEventListener('click', () => this._saveSchedule());

    const discardBtn = this.shadowRoot.getElementById('discard-btn');
    if (discardBtn) discardBtn.addEventListener('click', () => this._discardPending());

    // ── Grid drag/click listener (single delegated handler) ─────────────────
    const gridWrap = this.shadowRoot.querySelector('.grid-wrap');
    if (gridWrap) {
      gridWrap.addEventListener('mousedown', e => this._handleSlotMousedown(e));
    }
  }

  _renderHeader(title) {
    return `
      <div class="header">
        <span class="title">${escapeHtml(title)}</span>
        <button id="refresh-btn" class="icon-btn" title="Reload schedule from device"
                aria-label="Reload schedule">
          &#x21BB;
        </button>
      </div>
    `;
  }

  _renderVersionBanner() {
    const { serverVersion } = this._versionMismatch;
    return `
      <div class="banner banner-warn" role="alert">
        <span>
          Integration updated to v${escapeHtml(serverVersion)} — card cache is stale (v${escapeHtml(CARD_VERSION)}).
        </span>
        <button id="reload-btn" class="banner-btn">Clear cache &amp; reload</button>
      </div>
    `;
  }

  _renderSaveError() {
    return `
      <div class="banner banner-error" role="alert">
        <span>&#x26A0; ${escapeHtml(this._saveError)}</span>
      </div>
    `;
  }

  _renderActionBar() {
    if (this._saving) {
      return `
        <div class="action-bar">
          <span class="saving-msg">
            <span class="spinner-small"></span> Saving…
          </span>
        </div>
      `;
    }
    const count   = this._pending.size;
    const dayWord = count === 1 ? 'day' : 'days';
    return `
      <div class="action-bar">
        <span class="pending-msg">${escapeHtml(String(count))} ${dayWord} modified</span>
        <div class="action-btns">
          <button id="discard-btn" class="discard-btn">Discard</button>
          <button id="save-btn"    class="save-btn">Save</button>
        </div>
      </div>
    `;
  }

  _renderLoading() {
    return `<div class="loading"><div class="spinner"></div><span>Loading schedule…</span></div>`;
  }

  _renderError(message) {
    return `
      <div class="error">
        <span>&#x26A0; ${escapeHtml(message)}</span>
        <button id="retry-btn" class="retry-btn">Retry</button>
      </div>
    `;
  }

  _renderGrid() {
    const rows = [];

    // ── Time axis ──────────────────────────────────────────────────────────
    // Show hour labels every 2 hours (every 4 slots).
    const timeLabels = Array.from({ length: SLOT_COUNT }, (_, s) => {
      if (s % 4 === 0) {
        return `<div class="time-cell" style="grid-column:${s + 1}">${slotToTime(s)}</div>`;
      }
      return '';
    }).join('');

    rows.push(`
      <div class="day-row time-row">
        <div class="day-label"></div>
        <div class="slots-grid">${timeLabels}</div>
      </div>
    `);

    // ── Day rows ───────────────────────────────────────────────────────────
    for (let d = 0; d < 7; d++) {
      const isModified = this._pending.has(d);
      const daySlots   = this._getEffectiveSlots(d);
      const slotsHtml  = daySlots
        .map((mode, s) => {
          const info = MODES[mode] || MODES.off;
          const time = slotToTime(s);
          return `<div class="slot"
                       style="background:${info.color}"
                       title="${time} – ${info.label}"
                       data-day="${d}"
                       data-slot="${s}"></div>`;
        })
        .join('');

      const modMark = isModified
        ? `<span class="modified-mark" title="Unsaved changes">*</span>`
        : '';

      rows.push(`
        <div class="day-row">
          <div class="day-label${isModified ? ' day-modified' : ''}">${this._dayNames[d]}${modMark}</div>
          <div class="slots-grid slots-filled">${slotsHtml}</div>
        </div>
      `);
    }

    return `<div class="grid-wrap">${rows.join('')}</div>`;
  }

  _renderLegend() {
    const items = Object.entries(MODES)
      .map(([, info]) => `
        <span class="legend-item">
          <span class="legend-dot" style="background:${info.color}"></span>
          ${info.label}
        </span>`)
      .join('');
    return `
      <div class="legend">${items}</div>
      <div class="edit-hint">Click or drag slots to change mode</div>
    `;
  }

  // ── Styles ─────────────────────────────────────────────────────────────────

  _styles() {
    return `
      :host { display: block; }

      ha-card { overflow: hidden; }

      .card-content { padding: 12px 16px 16px; }

      /* ── Header ── */
      .header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 10px;
      }
      .title {
        font-size: 1em;
        font-weight: 500;
        color: var(--primary-text-color);
      }
      .icon-btn {
        background: none;
        border: none;
        cursor: pointer;
        font-size: 1.2em;
        color: var(--secondary-text-color);
        padding: 4px 6px;
        border-radius: 4px;
        line-height: 1;
        transition: color 0.15s, background 0.15s;
      }
      .icon-btn:hover {
        color: var(--primary-text-color);
        background: var(--secondary-background-color, rgba(0,0,0,0.06));
      }

      /* ── Banners (version mismatch / save error) ── */
      .banner {
        display: flex;
        justify-content: space-between;
        align-items: center;
        gap: 8px;
        padding: 8px 10px;
        border-radius: 6px;
        font-size: 0.82em;
        margin-bottom: 10px;
      }
      .banner-warn {
        background: var(--warning-color, #ff9800);
        color: #fff;
      }
      .banner-error {
        background: var(--error-color, #f44336);
        color: #fff;
      }
      .banner-btn {
        background: rgba(255,255,255,0.25);
        border: 1px solid rgba(255,255,255,0.5);
        border-radius: 4px;
        color: #fff;
        cursor: pointer;
        font-size: 0.9em;
        padding: 4px 8px;
        white-space: nowrap;
        flex-shrink: 0;
      }
      .banner-btn:hover { background: rgba(255,255,255,0.4); }

      /* ── Action bar (pending changes) ── */
      .action-bar {
        display: flex;
        justify-content: space-between;
        align-items: center;
        gap: 8px;
        padding: 7px 10px;
        margin-bottom: 10px;
        background: var(--secondary-background-color, rgba(0,0,0,0.04));
        border: 1px solid var(--divider-color, #e0e0e0);
        border-radius: 6px;
        font-size: 0.84em;
      }
      .pending-msg {
        color: var(--secondary-text-color);
      }
      .saving-msg {
        display: flex;
        align-items: center;
        gap: 8px;
        color: var(--secondary-text-color);
      }
      .action-btns {
        display: flex;
        gap: 8px;
      }
      .save-btn {
        background: var(--primary-color, #03a9f4);
        border: none;
        border-radius: 4px;
        color: #fff;
        cursor: pointer;
        font-size: 0.9em;
        font-weight: 500;
        padding: 5px 12px;
        transition: opacity 0.15s;
      }
      .save-btn:hover { opacity: 0.88; }
      .discard-btn {
        background: none;
        border: 1px solid var(--divider-color, #e0e0e0);
        border-radius: 4px;
        color: var(--secondary-text-color);
        cursor: pointer;
        font-size: 0.9em;
        padding: 5px 10px;
        transition: background 0.15s;
      }
      .discard-btn:hover {
        background: var(--secondary-background-color, rgba(0,0,0,0.06));
      }

      /* ── Loading ── */
      .loading {
        display: flex;
        align-items: center;
        gap: 10px;
        padding: 28px 0;
        color: var(--secondary-text-color);
        font-size: 0.9em;
      }
      .spinner, .spinner-small {
        border: 2px solid var(--divider-color, #e0e0e0);
        border-top-color: var(--primary-color, #03a9f4);
        border-radius: 50%;
        animation: spin 0.8s linear infinite;
        flex-shrink: 0;
      }
      .spinner { width: 20px; height: 20px; }
      .spinner-small { width: 13px; height: 13px; }
      @keyframes spin { to { transform: rotate(360deg); } }

      /* ── Error ── */
      .error {
        display: flex;
        flex-direction: column;
        align-items: flex-start;
        gap: 8px;
        padding: 16px 0;
        color: var(--error-color, #f44336);
        font-size: 0.88em;
      }
      .retry-btn {
        background: none;
        border: 1px solid currentColor;
        border-radius: 4px;
        color: inherit;
        cursor: pointer;
        font-size: 0.9em;
        padding: 4px 10px;
      }
      .retry-btn:hover { background: rgba(244,67,54,0.08); }

      /* ── Grid ── */
      .grid-wrap {
        overflow-x: auto;
        user-select: none; /* prevent text selection during drag */
      }

      .day-row {
        display: flex;
        align-items: center;
        min-height: 22px;
        margin-bottom: 2px;
      }

      .day-label {
        flex: 0 0 36px;
        font-size: 0.72em;
        font-weight: 500;
        color: var(--secondary-text-color);
        user-select: none;
      }
      .day-modified {
        color: var(--primary-color, #03a9f4);
      }
      .modified-mark {
        font-weight: 700;
        margin-left: 1px;
      }

      /* Shared slot-grid container — 48 equal columns */
      .slots-grid {
        flex: 1;
        display: grid;
        grid-template-columns: repeat(48, 1fr);
        min-width: 192px; /* 48 × 4px minimum — card scrolls below this */
        gap: 1px;
      }

      /* Time-axis row: only populated columns show labels */
      .time-row .slots-grid { min-height: 14px; }
      .time-cell {
        font-size: 0.6em;
        color: var(--secondary-text-color);
        white-space: nowrap;
        overflow: visible;
        user-select: none;
      }

      /* Coloured slot cells */
      .slots-filled .slot {
        height: 20px;
        border-radius: 2px;
        cursor: pointer;
        transition: opacity 0.1s, filter 0.1s;
      }
      .slots-filled .slot:hover {
        filter: brightness(1.15);
        opacity: 0.9;
      }

      /* ── Legend + edit hint ── */
      .legend {
        display: flex;
        gap: 14px;
        margin-top: 10px;
        flex-wrap: wrap;
      }
      .legend-item {
        display: flex;
        align-items: center;
        gap: 5px;
        font-size: 0.78em;
        color: var(--secondary-text-color);
      }
      .legend-dot {
        width: 11px;
        height: 11px;
        border-radius: 2px;
        flex-shrink: 0;
      }
      .edit-hint {
        margin-top: 5px;
        font-size: 0.72em;
        color: var(--disabled-text-color, #9e9e9e);
        font-style: italic;
      }
    `;
  }
}

// ─── Registration ─────────────────────────────────────────────────────────────

customElements.define('elios4you-scheduler-card', Elios4YouSchedulerCard);

window.customCards = window.customCards || [];
window.customCards.push({
  type: 'elios4you-scheduler-card',
  name: 'Elios4You Scheduler',
  description: 'Edit the Power Reducer weekly schedule (7 days × 48 slots). Click or drag to change modes.',
  preview: false,
  documentationURL: 'https://github.com/alexdelprete/ha-4noks-elios4you',
});
