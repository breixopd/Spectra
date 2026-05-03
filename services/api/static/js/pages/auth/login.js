/**
 * Login page: login form, MFA verification, password visibility toggle
 */
(function() {
    'use strict';

    window.toggleLoginPassword = function() {
        var p = document.getElementById('password');
        var isHidden = p.type === 'password';
        p.type = isHidden ? 'text' : 'password';
        var icon = document.getElementById('pw-toggle-icon');
        icon.setAttribute('data-lucide', isHidden ? 'eye-off' : 'eye');
        if (typeof lucide !== 'undefined') lucide.createIcons({nodes: [icon]});
    };

    if (new URLSearchParams(window.location.search).get('setup') === 'complete') {
        var successMsg = document.getElementById('success-msg');
        successMsg.textContent = 'Setup complete! Please log in with your admin credentials.';
        successMsg.classList.remove('hidden');
    }

    var mfaTempToken = null;
    var loginForm = document.getElementById('login-form');
    var mfaStep = document.getElementById('mfa-step');
    var loginFooter = document.getElementById('login-footer');
    var totpInput = document.getElementById('totp-code');
    var mfaSubmitBtn = document.getElementById('mfa-submit');
    var mfaCancelBtn = document.getElementById('mfa-cancel');
    var mfaErrorMsg = document.getElementById('mfa-error-msg');

    totpInput.addEventListener('input', function(e) {
        e.target.value = e.target.value.replace(/\D/g, '');
        if (e.target.value.length === 6) submitMfaCode();
    });

    window.showMfaStep = function() {
        loginForm.classList.add('hidden');
        loginFooter.classList.add('hidden');
        document.getElementById('error-msg').classList.add('hidden');
        document.getElementById('success-msg').classList.add('hidden');
        mfaStep.classList.remove('hidden');
        mfaErrorMsg.classList.add('hidden');
        totpInput.value = '';
        totpInput.focus();
    };

    window.showLoginForm = function() {
        if (mfaTempToken) {
            fetch('/api/v1/auth/mfa/cancel', {
                method: 'POST',
                headers: { 'Authorization': 'Bearer ' + mfaTempToken }
            }).catch(function() {});
        }
        mfaTempToken = null;
        mfaStep.classList.add('hidden');
        mfaErrorMsg.classList.add('hidden');
        totpInput.value = '';
        loginForm.classList.remove('hidden');
        loginFooter.classList.remove('hidden');
    };

    window.submitMfaCode = function() {
        var code = totpInput.value.trim();
        if (code.length !== 6 || !/^[0-9]{6}$/.test(code)) return;

        mfaSubmitBtn.disabled = true;
        mfaSubmitBtn.innerHTML = '<svg class="w-4 h-4 inline-block animate-spin mr-2" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83"/></svg>Verifying…';
        mfaErrorMsg.classList.add('hidden');

        fetch('/api/v1/auth/mfa/verify', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': 'Bearer ' + mfaTempToken,
                'X-Requested-With': 'XMLHttpRequest'
            },
            credentials: 'same-origin',
            body: JSON.stringify({ code: code })
        })
        .then(function(res) {
            if (!res.ok) {
                return res.json().then(function(errData) {
                    throw new Error(errData && errData.detail ? errData.detail : 'Invalid authentication code');
                });
            }
            mfaTempToken = null;
            window.location.href = '/dashboard';
        })
        .catch(function(err) {
            mfaSubmitBtn.disabled = false;
            mfaSubmitBtn.innerHTML = 'Verify';
            totpInput.value = '';
            totpInput.focus();
            mfaErrorMsg.textContent = err.message;
            mfaErrorMsg.classList.remove('hidden');
        });
    };

    mfaSubmitBtn.addEventListener('click', window.submitMfaCode);
    mfaCancelBtn.addEventListener('click', window.showLoginForm);

    totpInput.addEventListener('keydown', function(e) {
        if (e.key === 'Enter') {
            e.preventDefault();
            window.submitMfaCode();
        }
    });

    loginForm.onsubmit = function(e) {
        e.preventDefault();
        var formData = new FormData(e.target);
        var btn = e.target.querySelector('button[type="submit"]');
        var origHTML = btn.innerHTML;

        btn.disabled = true;
        btn.innerHTML = '<svg class="w-4 h-4 inline-block animate-spin mr-2" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83"/></svg>Signing in…';

        fetch('/api/v1/auth/token', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/x-www-form-urlencoded',
                'X-Requested-With': 'XMLHttpRequest'
            },
            credentials: 'same-origin',
            body: new URLSearchParams(formData)
        })
        .then(function(res) {
            if (!res.ok) throw new Error('Invalid credentials');
            return res.json();
        })
        .then(function(data) {
            if (data.mfa_required) {
                btn.disabled = false;
                btn.innerHTML = origHTML;
                mfaTempToken = data.access_token;
                window.showMfaStep();
                return;
            }
            window.location.href = '/dashboard';
        })
        .catch(function(err) {
            btn.disabled = false;
            btn.innerHTML = origHTML;
            var msg = document.getElementById('error-msg');
            msg.textContent = err.message;
            msg.classList.remove('hidden');
            msg.classList.add('text-red-400');
        });
    };
})();