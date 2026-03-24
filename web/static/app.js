/* ═══════════════════════════════════════════════════════════════
   Crypto RBI Bot — Global JavaScript
   ═══════════════════════════════════════════════════════════════ */

// ─── Clock ───────────────────────────────────────────────────
function updateClock() {
    const now = new Date();
    const hh = String(now.getHours()).padStart(2, '0');
    const mm = String(now.getMinutes()).padStart(2, '0');
    const ss = String(now.getSeconds()).padStart(2, '0');
    const el = document.getElementById('clock');
    if (el) el.textContent = `${hh}:${mm}:${ss}`;
}
setInterval(updateClock, 1000);
updateClock();

// ─── Number formatting ──────────────────────────────────────
function formatNum(value, decimals = 2) {
    if (value === null || value === undefined || isNaN(value)) return '—';
    const num = parseFloat(value);
    if (Math.abs(num) >= 1000) {
        return num.toLocaleString('en-US', {
            minimumFractionDigits: decimals,
            maximumFractionDigits: decimals
        });
    }
    return num.toFixed(decimals);
}

// ─── Toast Notifications ─────────────────────────────────────
function showToast(message, type = 'success') {
    const container = document.getElementById('toastContainer');
    if (!container) return;

    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.textContent = message;
    container.appendChild(toast);

    setTimeout(() => {
        toast.style.opacity = '0';
        toast.style.transform = 'translateX(100%)';
        toast.style.transition = 'all 0.3s ease';
        setTimeout(() => toast.remove(), 300);
    }, 3000);
}

// ─── Connection Status ───────────────────────────────────────
function updateConnectionStatus(connected) {
    const el = document.getElementById('connectionStatus');
    if (!el) return;

    const dot = el.querySelector('.status-dot');
    const text = el.querySelector('.status-text');

    if (connected) {
        dot.className = 'status-dot online';
        text.textContent = 'Connected';
    } else {
        dot.className = 'status-dot offline';
        text.textContent = 'Disconnected';
    }
}

// ─── Exchange Badge ──────────────────────────────────────────
async function updateExchangeBadge() {
    try {
        const res = await fetch('/api/settings');
        const data = await res.json();
        const badge = document.getElementById('exchangeBadge');
        if (badge && data.exchange_id) {
            badge.textContent = data.exchange_id.toUpperCase();
        }
    } catch (e) {}
}

// ─── Init ────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
    updateExchangeBadge();
});
