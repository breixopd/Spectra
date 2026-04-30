let _emailTemplates = {};
let _emailActiveTemplate = '';

async function loadEmailConfig() {
    const statusEl = document.getElementById('email-smtp-status');
    try {
        const r = await spectraApi.get('/api/admin/stats');
        const d = !r.error ? r.data : {};
        const smtpConfigured = Boolean(d.smtp_configured);
        statusEl.innerHTML = smtpConfigured
            ? '<span class="text-emerald-400"><i data-lucide="check-circle" class="w-4 h-4 inline-block mr-1"></i> SMTP configured</span>'
            : '<span class="text-amber-400"><i data-lucide="alert-triangle" class="w-4 h-4 inline-block mr-1"></i> SMTP not configured — using console fallback</span>';
        if (typeof lucide !== 'undefined') lucide.createIcons();
    } catch { statusEl.textContent = 'Unable to load status'; }

    try {
        const r = await spectraApi.get('/api/admin/email/templates');
        if (r.error) throw new Error();
        _emailTemplates = r.data;
        const tabs = document.getElementById('email-template-tabs');
        tabs.innerHTML = '';
        for (const name of Object.keys(_emailTemplates)) {
            const btn = document.createElement('button');
            btn.className = 'px-3 py-1 rounded-lg text-xs font-medium transition-colors ' +
                (name === _emailActiveTemplate ? 'bg-violet-600 text-white' : 'bg-white/5 text-slate-400 hover:bg-white/10');
            btn.textContent = name;
            btn.onclick = () => selectEmailTemplate(name);
            tabs.appendChild(btn);
        }
        if (!_emailActiveTemplate && Object.keys(_emailTemplates).length) {
            selectEmailTemplate(Object.keys(_emailTemplates)[0]);
        } else if (_emailActiveTemplate) {
            document.getElementById('email-template-editor').value = _emailTemplates[_emailActiveTemplate] || '';
        }
    } catch { /* ignore */ }
}

function selectEmailTemplate(name) {
    _emailActiveTemplate = name;
    document.getElementById('email-template-editor').value = _emailTemplates[name] || '';
    document.querySelectorAll('#email-template-tabs button').forEach(b => {
        b.className = b.textContent === name
            ? 'px-3 py-1 rounded-lg text-xs font-medium transition-colors bg-violet-600 text-white'
            : 'px-3 py-1 rounded-lg text-xs font-medium transition-colors bg-white/5 text-slate-400 hover:bg-white/10';
    });
}

async function saveEmailTemplate() {
    if (!_emailActiveTemplate) return;
    const content = document.getElementById('email-template-editor').value;
    try {
        const r = await spectraApi.put(`/api/admin/email/templates/${_emailActiveTemplate}`, {content});
        if (r.error) throw new Error(r.error);
        _emailTemplates[_emailActiveTemplate] = content;
        showConfirm('Template saved.', null, {title:'Saved', icon:'check', confirmText:'OK', hideCancel:true});
    } catch(e) { showConfirm(e.message, null, {title:'Error', icon:'triangle-exclamation', confirmText:'OK', hideCancel:true}); }
}

async function sendTestEmail(e) {
    e.preventDefault();
    const to = document.getElementById('test-email-to').value;
    const btn = document.getElementById('test-email-btn');
    const result = document.getElementById('test-email-result');
    btn.disabled = true; btn.textContent = 'Sending...';
    try {
        const r = await spectraApi.post('/api/admin/email/test', {to});
        const d = r.data;
        result.className = !r.error
            ? 'mt-3 p-3 rounded-lg text-sm bg-emerald-500/10 text-emerald-400 border border-emerald-500/20'
            : 'mt-3 p-3 rounded-lg text-sm bg-red-500/10 text-red-400 border border-red-500/20';
        result.textContent = !r.error ? `Test email sent to ${d.to}` : (r.error || 'Failed');
        result.classList.remove('hidden');
    } catch(err) {
        result.className = 'mt-3 p-3 rounded-lg text-sm bg-red-500/10 text-red-400 border border-red-500/20';
        result.textContent = err.message;
        result.classList.remove('hidden');
    } finally {
        btn.disabled = false; btn.innerHTML = '<i data-lucide="send" class="w-4 h-4 inline-block mr-1.5"></i> Send Test';
        if (typeof lucide !== 'undefined') lucide.createIcons();
    }
}

function _announcementPayload() {
    var titleEl = document.getElementById('announcement-title');
    var bodyEl = document.getElementById('announcement-body');
    var title = (titleEl && titleEl.value) ? titleEl.value.trim() : '';
    var content = bodyEl ? bodyEl.value : '';
    return { title: title, content: content };
}

function _setAnnouncementResult(ok, msg) {
    var result = document.getElementById('announcement-result');
    if (!result) return;
    result.className = ok
        ? 'mt-3 p-3 rounded-lg text-sm bg-emerald-500/10 text-emerald-400 border border-emerald-500/20'
        : 'mt-3 p-3 rounded-lg text-sm bg-red-500/10 text-red-400 border border-red-500/20';
    result.textContent = msg;
    result.classList.remove('hidden');
}

async function sendAnnouncementTest() {
    var payload = _announcementPayload();
    if (!payload.title) {
        _setAnnouncementResult(false, 'Enter a subject title.');
        return;
    }
    var btn = document.getElementById('announcement-test-btn');
    if (btn) { btn.disabled = true; btn.dataset.prevText = btn.innerHTML; btn.textContent = 'Sending...'; }
    try {
        var r = await spectraApi.post('/api/admin/email/announcement', {
            title: payload.title,
            content: payload.content,
            test_only: true,
        });
        if (r.error) {
            _setAnnouncementResult(false, r.error || 'Request failed');
        } else {
            var n = r.data && r.data.count != null ? r.data.count : 1;
            _setAnnouncementResult(true, 'Test announcement sent (' + n + '). Check your inbox.');
        }
    } catch (err) {
        _setAnnouncementResult(false, err.message || 'Failed');
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.innerHTML = btn.dataset.prevText || '<i data-lucide="mail" class="w-4 h-4 inline-block mr-1.5"></i> Send test to me';
            if (typeof lucide !== 'undefined') lucide.createIcons();
        }
    }
}

async function _postAnnouncementBroadcast() {
    var payload = _announcementPayload();
    if (!payload.title) {
        _setAnnouncementResult(false, 'Enter a subject title.');
        return;
    }
    var btn = document.getElementById('announcement-send-all-btn');
    if (btn) { btn.disabled = true; btn.dataset.prevText = btn.innerHTML; btn.textContent = 'Sending...'; }
    try {
        var r = await spectraApi.post('/api/admin/email/announcement', {
            title: payload.title,
            content: payload.content,
            test_only: false,
        });
        if (r.error) {
            _setAnnouncementResult(false, r.error || 'Request failed');
        } else {
            var c = r.data && r.data.count != null ? r.data.count : 0;
            _setAnnouncementResult(true, 'Queued sends completed. Messages accepted: ' + c + '.');
        }
    } catch (err) {
        _setAnnouncementResult(false, err.message || 'Failed');
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.innerHTML = btn.dataset.prevText || '<i data-lucide="megaphone" class="w-4 h-4 inline-block mr-1.5"></i> Send to opted-in users';
            if (typeof lucide !== 'undefined') lucide.createIcons();
        }
    }
}

function confirmSendAnnouncementToAll() {
    var payload = _announcementPayload();
    if (!payload.title) {
        _setAnnouncementResult(false, 'Enter a subject title.');
        return;
    }
    showConfirm(
        'Send announcement',
        'Send this announcement to all active users who opted in?',
        function () { void _postAnnouncementBroadcast(); },
    );
}
