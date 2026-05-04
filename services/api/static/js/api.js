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

const spectraApi = (() => {
    'use strict';

    let _activeRequests = 0;

    const publicPaths = window.PUBLIC_PATHS || [];

    function _getDecodedCookieValue(name) {
        const match = document.cookie.match(new RegExp(`(?:^|; )${name}=([^;]+)`));
        if (!match) return null;
        try {
            return decodeURIComponent(match[1]);
        } catch (_) {
            return match[1];
        }
    }

    function _clearSpectraLocalStorage() {
        Object.keys(localStorage)
            .filter(key => key.startsWith('spectra_'))
            .forEach(key => localStorage.removeItem(key));
    }

    function _onLoadingChange(count) {
        const el = document.getElementById('spectra-api-loading');
        if (el) {
            el.style.display = count > 0 ? 'block' : 'none';
        }
    }

    let _refreshing = false;
    let _refreshQueue = [];

    async function _attemptTokenRefresh() {
        // Prevent concurrent refresh loops — queue callers until the in-flight refresh resolves
        if (_refreshing) {
            return new Promise(resolve => _refreshQueue.push(resolve));
        }
        _refreshing = true;
        try {
            const res = await fetch('/api/v1/auth/refresh', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'same-origin',
                body: JSON.stringify({}),  // cookie carries the refresh token
            });
            const ok = res.status === 200;
            _refreshQueue.forEach(resolve => resolve(ok));
            _refreshQueue = [];
            return ok;
        } catch {
            _refreshQueue.forEach(resolve => resolve(false));
            _refreshQueue = [];
            return false;
        } finally {
            _refreshing = false;
        }
    }

    /**
     * Core request method.
     * Returns { data, response, error } — never throws.
     */
    async function request(url, options = {}) {
        const headers = { ...options.headers };

        if (options.body && typeof options.body === 'object' && !(options.body instanceof FormData)) {
            headers['Content-Type'] = 'application/json';
            options.body = JSON.stringify(options.body);
        }

        // CSRF token from cookie (double-submit pattern)
        const csrfToken = _getDecodedCookieValue('csrf_token');
        if (csrfToken && ['POST', 'PUT', 'DELETE', 'PATCH'].includes((options.method || 'GET').toUpperCase())) {
            headers['X-CSRF-Token'] = csrfToken;
        }

        _activeRequests++;
        _onLoadingChange(_activeRequests);

        const controller = new AbortController();
        const timeoutId = window.setTimeout(() => controller.abort(), 30000);
        try {
            const response = await fetch(url, { ...options, headers, credentials: 'same-origin', signal: controller.signal });

            // Handle auth failures
            if (response.status === 401 && !publicPaths.includes(window.location.pathname) && !options._isRetry) {
                // Attempt silent token refresh before redirecting
                const refreshed = await _attemptTokenRefresh();
                if (refreshed) {
                    _activeRequests--;
                    _onLoadingChange(_activeRequests);
                    return request(url, { ...options, _isRetry: true });
                }
                _clearSpectraLocalStorage();
                window.location.href = '/login';
                return { data: null, response, error: 'Unauthorized', status: response.status };
            }

            if (response.status === 429) {
                const msg = 'Rate limit exceeded — please wait and try again';
                if (typeof showToast === 'function') {
                    showToast(msg, 'warning');
                }
                return { data: null, response, error: msg, status: response.status };
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
                return { data, response, error: detail, status: response.status };
            }

            return { data, response, error: null, status: response.status };
        } catch (err) {
            const message = err && err.name === 'AbortError' ? 'Request timed out' : (err.message || 'Network error');
            return { data: null, response: null, error: message, status: null };
        } finally {
            window.clearTimeout(timeoutId);
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

window.clearSpectraLocalStorage = function() {
    try {
        Object.keys(localStorage)
            .filter(key => key.startsWith('spectra_'))
            .forEach(key => localStorage.removeItem(key));
    } catch (_) {}
};
