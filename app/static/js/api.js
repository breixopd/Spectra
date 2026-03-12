/**
 * Spectra API Client — centralized fetch wrapper.
 *
 * Provides consistent auth header injection, error handling, and
 * JSON parsing for all API calls. Available globally as `spectraApi`.
 *
 * Usage:
 *   const { data, error } = await spectraApi.get('/api/v1/missions');
 *   const { data, error } = await spectraApi.post('/api/v1/targets', { ip: '10.0.0.1' });
 */

/**
 * Debounce function - delays invoking func until after wait ms have elapsed
 * since the last time the debounced function was invoked.
 */
function debounce(func, wait = 300) {
    let timeoutId;
    return function(...args) {
        clearTimeout(timeoutId);
        timeoutId = setTimeout(() => func.apply(this, args), wait);
    };
}
window.debounce = debounce;

/**
 * Escape HTML special characters to prevent XSS.
 * @param {string} str - The string to escape.
 * @returns {string} The escaped string.
 */
function escapeHtml(str) {
    if (typeof str !== 'string') return str;
    const div = document.createElement('div');
    div.appendChild(document.createTextNode(str));
    return div.innerHTML;
}
window.escapeHtml = escapeHtml;

const spectraApi = (() => {
    'use strict';

    let _activeRequests = 0;

    function _getToken() {
        return localStorage.getItem('token') || '';
    }

    function _onLoadingChange(count) {
        const el = document.getElementById('spectra-api-loading');
        if (el) {
            el.style.display = count > 0 ? 'block' : 'none';
        }
    }

    /**
     * Core request method.
     * Returns { data, response, error } — never throws.
     */
    async function request(url, options = {}) {
        const token = _getToken();
        const headers = { ...options.headers };

        if (token && !url.includes('/token')) {
            headers['Authorization'] = `Bearer ${token}`;
        }

        if (options.body && typeof options.body === 'object' && !(options.body instanceof FormData)) {
            headers['Content-Type'] = 'application/json';
            options.body = JSON.stringify(options.body);
        }

        _activeRequests++;
        _onLoadingChange(_activeRequests);

        try {
            const response = await fetch(url, { ...options, headers });

            // Handle auth failures
            const publicPaths = ['/login', '/setup'];
            if (response.status === 401 && !publicPaths.includes(window.location.pathname)) {
                localStorage.removeItem('token');
                window.location.href = '/login';
                return { data: null, response, error: 'Unauthorized' };
            }

            if (response.status === 429) {
                const msg = 'Rate limit exceeded — please wait and try again';
                if (typeof _spectraToast === 'function') {
                    _spectraToast(msg, 'warning');
                }
                return { data: null, response, error: msg };
            }

            if (response.status === 422) {
                const msg = 'Invalid input — please check the form fields';
                if (typeof _spectraToast === 'function') {
                    _spectraToast(msg, 'warning');
                }
            }

            if (response.status >= 500) {
                const msg = 'Server error — please try again later';
                if (typeof _spectraToast === 'function') {
                    _spectraToast(msg, 'error');
                }
            }

            // Parse JSON if content-type indicates it
            const ct = response.headers.get('content-type') || '';
            let data = null;
            if (ct.includes('application/json')) {
                data = await response.json();
            } else {
                data = await response.text();
            }

            if (!response.ok) {
                const detail = (typeof data === 'object' && data !== null && data.detail) || `HTTP ${response.status}`;
                return { data, response, error: detail };
            }

            return { data, response, error: null };
        } catch (err) {
            return { data: null, response: null, error: err.message || 'Network error' };
        } finally {
            _activeRequests--;
            _onLoadingChange(_activeRequests);
        }
    }

    return {
        request,

        get(url, options = {}) {
            return request(url, { ...options, method: 'GET' });
        },

        post(url, body, options = {}) {
            return request(url, { ...options, method: 'POST', body });
        },

        put(url, body, options = {}) {
            return request(url, { ...options, method: 'PUT', body });
        },

        delete(url, options = {}) {
            return request(url, { ...options, method: 'DELETE' });
        },

        /** Number of in-flight requests */
        get loading() {
            return _activeRequests > 0;
        },
    };
})();
