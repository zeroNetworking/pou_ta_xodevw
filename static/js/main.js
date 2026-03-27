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
    const year = document.getElementById('newYearInput').value;
    fetch('/new_month', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({month, year})
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
    // Αποθήκευση στο sessionStorage ώστε να μην ξαναεμφανιστεί στην ίδια session
    sessionStorage.setItem('suggestDismissed', '1');
}
function confirmSuggestMonth(month, year) {
    fetch('/new_month', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({month, year})
    })
    .then(r => r.json())
    .then(d => {
        if (d.month_id) window.location.href = `/month/${d.month_id}`;
    });
}
// Αν ο χρήστης το είχε κλείσει νωρίτερα στην ίδια session, μην το δείχνεις
if (sessionStorage.getItem('suggestDismissed')) {
    const el = document.getElementById('suggestMonthModal');
    if (el) el.classList.remove('active');
}

// ── Generic Modal helpers ────────────────────────────────────
function closeModalOnOverlay(event) {
    if (event.target === event.currentTarget) {
        event.currentTarget.classList.remove('active');
    }
}
document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape') {
        document.querySelectorAll('.modal-overlay.active').forEach(m => {
            // Μην κλείνει το suggest modal με Escape
            if (m.id !== 'suggestMonthModal') m.classList.remove('active');
        });
    }
});

// ── Privacy Toggle ───────────────────────────────────────────
// Αποθηκεύεται στο localStorage ώστε να θυμάται μεταξύ σελίδων
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

// Εφαρμογή κατά το φόρτωμα σελίδας
(function() {
    const stored = localStorage.getItem(PRIVACY_KEY);
    if (stored === '1') applyPrivacy(true);
})();
