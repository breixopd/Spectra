/**
 * Shared utility functions for Spectra pages.
 */

/**
 * Format an ISO date string for display.
 * @param {string} iso - ISO 8601 date string.
 * @param {{ time?: boolean }} options - Include time.
 * @returns {string}
 */
export function formatDate(iso, options = {}) {
    if (!iso) return '—';
    const d = new Date(iso);
    if (options.time) {
        return d.toLocaleString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
    }
    return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
}

/**
 * Throttle a function — calls at most once per wait ms.
 * @param {Function} func
 * @param {number} wait
 * @returns {Function}
 */
export function throttle(func, wait = 200) {
    let last = 0;
    let timeoutId;
    return function(...args) {
        const now = Date.now();
        const remaining = wait - (now - last);
        clearTimeout(timeoutId);
        if (remaining <= 0) {
            last = now;
            func.apply(this, args);
        } else {
            timeoutId = setTimeout(() => {
                last = Date.now();
                func.apply(this, args);
            }, remaining);
        }
    };
}

/**
 * Validate password against backend rules.
 * @param {string} password
 * @returns {{ valid: boolean, errors: string[] }}
 */
export function validatePassword(password) {
    const errors = [];
    if (password.length < 8) errors.push('At least 8 characters');
    if (!/[A-Z]/.test(password)) errors.push('At least one uppercase letter');
    if (!/[a-z]/.test(password)) errors.push('At least one lowercase letter');
    if (!/[0-9]/.test(password)) errors.push('At least one digit');
    return { valid: errors.length === 0, errors };
}
window.validatePassword = validatePassword;

// Re-export escapeHtml (defined in base.html, available globally)
export const escapeHtml = window.escapeHtml || function(s) {
    const d = document.createElement('div');
    d.textContent = s;
    return d.innerHTML;
};

// Re-export debounce (defined in api.js, available globally)
export const debounce = window.debounce || function(func, wait = 300) {
    let timeoutId;
    return function(...args) {
        clearTimeout(timeoutId);
        timeoutId = setTimeout(() => func.apply(this, args), wait);
    };
};
