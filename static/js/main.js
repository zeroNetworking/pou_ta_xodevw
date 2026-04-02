// ============================================================
// CSRF Token — FIX #7
// Fetched once on page load from /api/csrf_token.
// Sent as X-CSRF-Token header on every state-changing fetch call.
// This protects all JSON endpoints from CSRF attacks.
// ============================================================
let _csrfToken = null;

async function getCsrfToken() {
    // Return cached token if available
    if (_csrfToken) return _csrfToken;
    try {
        const r = await fetch('/api/csrf_token');
        const d = await r.json();
        _csrfToken = d.csrf_token;
    } catch (e) {
        console.error('Failed to fetch CSRF token', e);
    }
    return _csrfToken;
}

/**
 * Drop-in replacement for fetch() that automatically adds:
 * - Content-Type: application/json
 * - X-CSRF-Token header (for POST/PUT/DELETE)
 * Usage: apiFetch('/add_transaction', { method: 'POST', body: data })
 */
async function apiFetch(url, options = {}) {
    const method = (options.method || 'GET').toUpperCase();
    const headers = { ...(options.headers || {}) };

    // Add CSRF token for all state-changing methods
    if (['POST', 'PUT', 'DELETE', 'PATCH'].includes(method)) {
        const token = await getCsrfToken();
        if (token) headers['X-CSRF-Token'] = token;
        if (!headers['Content-Type'] && options.body) {
            headers['Content-Type'] = 'application/json';
        }
    }

    return fetch(url, { ...options, headers });
}

// ── Live Clock ──────────────────────────────────────────────
function updateClock() {
    const now = new Date();
    const pad = n => String(n).padStart(2, '0');
    const timeEl = document.getElementById('clockTime');
    const dateEl = document.getElementById('clockDate');
    if (timeEl) timeEl.textContent = `${pad(now.getHours())}:${pad(now.getMinutes())}:${pad(now.getSeconds())}`;
    if (dateEl) {
        const days = ['Κυρ', 'Δευ', 'Τρι', 'Τετ', 'Πεμ', 'Παρ', 'Σαβ'];
        dateEl.textContent = `${days[now.getDay()]} ${pad(now.getDate())}/${pad(now.getMonth()+1)}/${now.getFullYear()}`;
    }
}
updateClock();
setInterval(updateClock, 1000);

// ── New Month Modal ──────────────────────────────────────────
function openNewMonthModal() {
    const d = new Date();
    document.getElementById('newMonthSelect').value = d.getMonth() + 1;
    document.getElementById('newYearInput').value = d.getFullYear();
    document.getElementById('newMonthModal').classList.add('active');
}
function closeNewMonthModal() {
    document.getElementById('newMonthModal').classList.remove('active');
}
function createNewMonth() {
    const month = document.getElementById('newMonthSelect').value;
    const year  = document.getElementById('newYearInput').value;
    // Uses apiFetch to automatically include X-CSRF-Token header
    apiFetch('/new_month', {
        method: 'POST',
        body: JSON.stringify({ month, year })
    })
    .then(r => r.json())
    .then(d => {
        if (d.success || d.month_id) {
            window.location.href = `/month/${d.month_id}`;
        } else {
            alert(d.error || 'Σφάλμα');
        }
    });
}

// ── Suggest New Month Modal ──────────────────────────────────
function dismissSuggest() {
    const el = document.getElementById('suggestMonthModal');
    if (el) el.classList.remove('active');
    sessionStorage.setItem('suggestDismissed', '1');
}
function confirmSuggestMonth(month, year) {
    apiFetch('/new_month', {
        method: 'POST',
        body: JSON.stringify({ month, year })
    })
    .then(r => r.json())
    .then(d => {
        if (d.month_id) window.location.href = `/month/${d.month_id}`;
    });
}
if (sessionStorage.getItem('suggestDismissed')) {
    const el = document.getElementById('suggestMonthModal');
    if (el) el.classList.remove('active');
}

// ── Generic Modal Helpers ────────────────────────────────────
function closeModalOnOverlay(event) {
    if (event.target === event.currentTarget) {
        event.currentTarget.classList.remove('active');
    }
}
document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape') {
        document.querySelectorAll('.modal-overlay.active').forEach(m => {
            if (m.id !== 'suggestMonthModal') m.classList.remove('active');
        });
    }
});

// ── Privacy Toggle ───────────────────────────────────────────
const PRIVACY_KEY = 'financePrivacyMode';

function applyPrivacy(hidden) {
    const btn = document.getElementById('privacyToggle');
    if (hidden) {
        document.body.classList.add('privacy-mode');
        if (btn) { btn.textContent = '🙈'; btn.title = 'Εμφάνιση ποσών'; }
    } else {
        document.body.classList.remove('privacy-mode');
        if (btn) { btn.textContent = '👁'; btn.title = 'Απόκρυψη ποσών'; }
    }
}
function togglePrivacy() {
    const isHidden = document.body.classList.contains('privacy-mode');
    const newState = !isHidden;
    localStorage.setItem(PRIVACY_KEY, newState ? '1' : '0');
    applyPrivacy(newState);
}
(function() {
    if (localStorage.getItem(PRIVACY_KEY) === '1') applyPrivacy(true);
})();

// ── Dark Mode ───────────────────────────────────────────────
// Global dark mode functions — toggle button is in index.html header,
// but the state persists via localStorage and the inline <script> in base.html.
const DARK_KEY = 'financeDarkMode';
function applyDarkMode(dark) {
    document.documentElement.setAttribute('data-theme', dark ? 'dark' : 'light');
    const btn = document.getElementById('darkToggleBtn');
    if (btn) btn.textContent = dark ? '☀️' : '🌙';
    localStorage.setItem(DARK_KEY, dark ? '1' : '0');
}
function toggleDarkMode() {
    const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
    applyDarkMode(!isDark);
}
// Sync button state on page load (the data-theme attribute is set in base.html <head>)
(function() {
    if (localStorage.getItem(DARK_KEY) === '1') {
        const btn = document.getElementById('darkToggleBtn');
        if (btn) btn.textContent = '☀️';
    }
})();

// ── Density (Compact / Comfortable) ─────────────────────────
const DENSITY_KEY = 'financeDensity';
function applyDensity(density) {
    document.documentElement.setAttribute('data-density', density);
    localStorage.setItem(DENSITY_KEY, density);
}
// Ensure density is applied (base.html <head> handles initial, this is a safety net)
(function() {
    const d = localStorage.getItem(DENSITY_KEY) || 'comfortable';
    document.documentElement.setAttribute('data-density', d);
})();

// ── Mobile Sidebar Drawer ────────────────────────────────────
function toggleMobileDrawer() {
    const sidebar = document.getElementById('sidebar');
    const overlay = document.getElementById('mobileOverlay');
    const isOpen  = sidebar.classList.contains('drawer-open');
    if (isOpen) {
        closeMobileDrawer();
    } else {
        sidebar.classList.add('drawer-open');
        overlay.classList.add('active');
        document.body.classList.add('drawer-is-open');
    }
}
function closeMobileDrawer() {
    document.getElementById('sidebar').classList.remove('drawer-open');
    document.getElementById('mobileOverlay').classList.remove('active');
    document.body.classList.remove('drawer-is-open');
}
document.addEventListener('DOMContentLoaded', function () {
    document.querySelectorAll('.sidebar .nav-item').forEach(function (link) {
        link.addEventListener('click', function () {
            if (window.innerWidth <= 768) closeMobileDrawer();
        });
    });

    // Auto-expand months list if we're currently viewing a month
    const hasActiveMonth = document.querySelector('.nav-months-list .nav-month.active');
    if (hasActiveMonth) {
        const list = document.getElementById('monthsList');
        const arrow = document.getElementById('monthsArrow');
        if (list) list.classList.remove('collapsed');
        if (arrow) arrow.textContent = '▾';
    }
});

// ── Sidebar Months Collapse ─────────────────────────────────
function toggleMonthsList() {
    const list  = document.getElementById('monthsList');
    const arrow = document.getElementById('monthsArrow');
    const isCollapsed = list.classList.contains('collapsed');
    list.classList.toggle('collapsed');
    arrow.textContent = isCollapsed ? '▾' : '▸';
}

// ── Calculator ──────────────────────────────────────────────
let _calcCurrent = '0';
let _calcPrev = '';
let _calcOp = '';
let _calcReset = false;

function openCalcModal() {
    document.getElementById('calcModal').classList.add('active');
}
function closeCalcModal() {
    document.getElementById('calcModal').classList.remove('active');
}

function _calcUpdate() {
    document.getElementById('calcResult').textContent = _calcCurrent;
    document.getElementById('calcExpr').textContent = _calcPrev ? `${_calcPrev} ${_calcOpSymbol(_calcOp)}` : '\u00a0';
}
function _calcOpSymbol(op) {
    return { '+': '+', '-': '−', '*': '×', '/': '÷' }[op] || '';
}

function calcDigit(d) {
    if (_calcReset) { _calcCurrent = '0'; _calcReset = false; }
    if (_calcCurrent === '0' && d !== '.') _calcCurrent = d;
    else if (_calcCurrent.length < 15) _calcCurrent += d;
    _calcUpdate();
}

function calcDot() {
    if (_calcReset) { _calcCurrent = '0'; _calcReset = false; }
    if (!_calcCurrent.includes('.')) _calcCurrent += '.';
    _calcUpdate();
}

function calcOp(op) {
    if (_calcPrev && _calcOp && !_calcReset) {
        calcEquals();
    }
    _calcPrev = _calcCurrent;
    _calcOp = op;
    _calcReset = true;
    _calcUpdate();
}

function calcEquals() {
    if (!_calcOp || !_calcPrev) return;
    const a = parseFloat(_calcPrev);
    const b = parseFloat(_calcCurrent);
    let result = 0;
    switch (_calcOp) {
        case '+': result = a + b; break;
        case '-': result = a - b; break;
        case '*': result = a * b; break;
        case '/': result = b !== 0 ? a / b : 'Error'; break;
    }
    if (typeof result === 'number') {
        // Round to avoid floating point display issues
        result = parseFloat(result.toPrecision(12));
    }
    _calcCurrent = String(result);
    _calcPrev = '';
    _calcOp = '';
    _calcReset = true;
    _calcUpdate();
}

function calcClear() {
    _calcCurrent = '0';
    _calcPrev = '';
    _calcOp = '';
    _calcReset = false;
    _calcUpdate();
}

function calcBackspace() {
    if (_calcReset) return;
    _calcCurrent = _calcCurrent.length > 1 ? _calcCurrent.slice(0, -1) : '0';
    _calcUpdate();
}

function calcPercent() {
    _calcCurrent = String(parseFloat(_calcCurrent) / 100);
    _calcUpdate();
}

// Keyboard support when calculator is open
document.addEventListener('keydown', function(e) {
    if (!document.getElementById('calcModal').classList.contains('active')) return;
    if (e.key >= '0' && e.key <= '9') calcDigit(e.key);
    else if (e.key === '.') calcDot();
    else if (e.key === '+') calcOp('+');
    else if (e.key === '-') calcOp('-');
    else if (e.key === '*') calcOp('*');
    else if (e.key === '/') { e.preventDefault(); calcOp('/'); }
    else if (e.key === 'Enter' || e.key === '=') calcEquals();
    else if (e.key === 'Backspace') calcBackspace();
    else if (e.key === 'Escape') closeCalcModal();
    else if (e.key.toLowerCase() === 'c') calcClear();
});
