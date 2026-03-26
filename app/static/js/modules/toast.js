/**
 * Toast notification module.
 * Re-exports the global _spectraToast for use as an ES module import.
 */

/**
 * Show a toast notification.
 * @param {string} msg - Message to display.
 * @param {string} type - 'success', 'error', 'warning', 'info'.
 */
export function showToast(msg, type = 'success') {
    if (typeof _spectraToast === 'function') {
        _spectraToast(msg, type);
    }
}
