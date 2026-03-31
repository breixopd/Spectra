(function() {
    if (window.__spectraCookieConsentInitialized) {
        return;
    }
    window.__spectraCookieConsentInitialized = true;

    function getConsentCookie() {
        var match = document.cookie.match(/(?:^|; )cookie_consent=([^;]+)/);
        if (!match) {
            return null;
        }
        try {
            return decodeURIComponent(match[1]);
        } catch (_error) {
            return match[1];
        }
    }

    function acceptCookies(level) {
        var secure = window.location.protocol === 'https:' ? ';Secure' : '';
        document.cookie = 'cookie_consent=' + encodeURIComponent(level) + ';path=/;max-age=31536000;SameSite=Lax' + secure;
        var banner = document.getElementById('cookie-consent');
        if (banner) {
            banner.classList.add('is-hidden');
        }
    }

    function initCookieConsent() {
        var banner = document.getElementById('cookie-consent');
        if (!banner) {
            return;
        }

        banner.querySelectorAll('[data-cookie-consent]').forEach(function(button) {
            button.addEventListener('click', function() {
                acceptCookies(button.getAttribute('data-cookie-consent') || 'essential');
            });
        });

        if (!getConsentCookie()) {
            banner.classList.remove('is-hidden');
        }
    }

    initCookieConsent();
})();