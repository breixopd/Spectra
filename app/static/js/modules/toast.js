/**
 * Toast notification system — canonical implementation.
 * Exposes showToast() as the module API.
 * Also sets window._spectraToast for legacy callers.
 */

const TOAST_TYPES = {
    success: 'background:rgba(16,185,129,0.15);border:1px solid rgba(16,185,129,0.3);color:#34d399;',
    error: 'background:rgba(239,68,68,0.15);border:1px solid rgba(239,68,68,0.3);color:#f87171;',
    warning: 'background:rgba(245,158,11,0.15);border:1px solid rgba(245,158,11,0.3);color:#fbbf24;',
    info: 'background:rgba(96,165,250,0.15);border:1px solid rgba(96,165,250,0.3);color:#60a5fa;',
};

function _getOrCreateContainer() {
    let c = document.getElementById('spectra-toast-container');
    if (!c) {
        c = document.createElement('div');
        c.id = 'spectra-toast-container';
        c.setAttribute('aria-live', 'assertive');
        c.setAttribute('role', 'alert');
        c.setAttribute('aria-atomic', 'false');
        c.style.cssText = 'position:fixed;top:1rem;right:1rem;z-index:9999;display:flex;flex-direction:column;gap:0.5rem;max-width:360px;pointer-events:none;';
        document.body.appendChild(c);
    }
    return c;
}

export function showToast(msg, type = 'info') {
    const c = _getOrCreateContainer();
    const el = document.createElement('div');
    el.setAttribute('role', 'status');
    el.style.cssText = 'padding:0.75rem 1rem;border-radius:0.5rem;font-size:0.85rem;font-weight:500;backdrop-filter:blur(8px);pointer-events:auto;'
        + (TOAST_TYPES[type] || TOAST_TYPES.info);
    el.textContent = msg;
    // Slide in
    el.style.opacity = '0';
    el.style.transform = 'translateX(1rem)';
    el.style.transition = 'opacity 0.2s ease, transform 0.2s ease';
    c.appendChild(el);
    requestAnimationFrame(() => {
        el.style.opacity = '1';
        el.style.transform = 'translateX(0)';
    });
    // Auto-remove
    const timer = setTimeout(() => {
        el.style.opacity = '0';
        el.style.transform = 'translateX(1rem)';
        setTimeout(() => el.remove(), 200);
    }, 5000);
    el.addEventListener('click', () => { clearTimeout(timer); el.remove(); });
}

// Expose as global for legacy callers and base.html inline script
window._spectraToast = showToast;

// Drain any toasts queued before module loaded
if (Array.isArray(window._toastQueue)) {
    window._toastQueue.forEach(({ msg, type }) => showToast(msg, type));
    window._toastQueue = [];
}
