/**
 * Spectra API Client — centralized fetch wrapper.
 *
 * Provides consistent auth header injection, error handling, and
 * JSON parsing for all API calls. Available globally as `spectraApi`.
 *
 * Usage:
 *   const { data, error } = await spectraApi.get('/api/missions');
 *   const { data, error } = await spectraApi.post('/api/targets', { ip: '10.0.0.1' });
 */
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
