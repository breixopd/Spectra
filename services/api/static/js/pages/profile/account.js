async function loadProfile() {
    try {
        const { data: user, error } = await spectraApi.get('/api/v1/auth/me');
        if (error) throw new Error(error);
        clearProfileLoadError();
        document.getElementById('profile-username').value = user.username || '';
        document.getElementById('profile-email').value = user.email || '';
        document.getElementById('profile-role').value = (user.role || 'operator').charAt(0).toUpperCase() + (user.role || 'operator').slice(1);
    } catch (e) {
        console.error('Failed to load profile', e);
        showProfileLoadError(`Unable to load your profile right now. ${e.message || 'Please try again.'}`);
    }
}

async function saveProfile() {
    const email = document.getElementById('profile-email').value;
    try {
        const { error } = await spectraApi.put('/api/v1/auth/me', { email });
        if (!error) showToast('Profile updated');
        else showToast('Failed to update profile', 'error');
    } catch (e) { showToast('Network error', 'error'); }
}

(function() {
    const npw = document.getElementById('new-password');
    if (!npw) return;
    function _upd(id, pass) {
        const el = document.getElementById(id);
        if (!el) return;
        el.style.color = pass ? '#34d399' : '#94a3b8';
        el.querySelector('.pw-req-icon').innerHTML = pass ? '&#x2713;' : '&#x2717;';
    }
    npw.addEventListener('input', () => {
        const v = npw.value;
        _upd('profile-pw-len', v.length >= 8);
        _upd('profile-pw-upper', /[A-Z]/.test(v));
        _upd('profile-pw-lower', /[a-z]/.test(v));
        _upd('profile-pw-digit', /[0-9]/.test(v));
    });
})();

async function changePassword() {
    const current = document.getElementById('current-password').value;
    const newPw = document.getElementById('new-password').value;
    const confirm = document.getElementById('confirm-password').value;
    if (!current || !newPw) return showToast('Please fill all fields', 'error');
    if (newPw !== confirm) return showToast('Passwords do not match', 'error');
    if (newPw.length < 8 || !/[A-Z]/.test(newPw) || !/[a-z]/.test(newPw) || !/[0-9]/.test(newPw)) {
        return showToast('Password must be at least 8 characters with uppercase, lowercase, and a digit', 'error');
    }
    try {
        const { error } = await spectraApi.post('/api/v1/auth/change-password', { current_password: current, new_password: newPw });
        if (!error) {
            showToast('Password changed successfully');
            document.getElementById('current-password').value = '';
            document.getElementById('new-password').value = '';
            document.getElementById('confirm-password').value = '';
        } else {
            showToast(error || 'Failed to change password', 'error');
        }
    } catch (e) { showToast('Network error', 'error'); }
}

async function deleteAccount() {
    _spectraPrompt('Type your password to confirm account deletion:', (pw) => {
        _spectraConfirm('Are you absolutely sure? This will permanently delete your account and ALL data.', async () => {
            try {
                const { data, error } = await spectraApi.request('/api/v1/auth/account', { method: 'DELETE', body: { password: pw } });
                if (!error) {
                    window.location.href = '/login?msg=account_deleted';
                } else {
                    showToast(error || 'Failed to delete account', 'error');
                }
            } catch (e) { showToast('Network error', 'error'); }
        }, { title: 'Delete Account', confirmLabel: 'Delete Permanently' });
    }, { title: 'Account Deletion', inputType: 'password', placeholder: 'Enter your password', confirmLabel: 'Continue' });
}

loadProfile();

window.saveProfile = saveProfile;
window.deleteAccount = deleteAccount;
window.changePassword = changePassword;
