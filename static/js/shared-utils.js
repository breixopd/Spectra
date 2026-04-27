window.formatDate = function(iso, opts) {
    if (!iso) return '—';
    const d = new Date(iso);
    if (opts && opts.time) {
        return d.toLocaleString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
    }
    return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
};

window.formatDateTime = function(iso) {
    return window.formatDate(iso, { time: true });
};

window.formatBytes = function(b) {
    if (!b) return '0 B';
    const k = 1024, s = ['B', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(b) / Math.log(k));
    return (b / Math.pow(k, i)).toFixed(1) + ' ' + s[i];
};

window.showSharedModal = function(id) {
    if (typeof window.showModal === 'function') {
        window.showModal(id);
        return;
    }
    document.getElementById(id)?.classList.remove('hidden');
};

window.closeSharedModal = function(id) {
    if (typeof window.closeModal === 'function') {
        window.closeModal(id);
        return;
    }
    document.getElementById(id)?.classList.add('hidden');
};

window.colorizeOutput = function(text) {
    return text
        .replace(/(\[(\+|SUCCESS|FOUND|open)\])/gi, '<span class="text-emerald-400">$1</span>')
        .replace(/(\[(-|FAIL|ERROR|closed)\])/gi, '<span class="text-rose-400">$1</span>')
        .replace(/(\[(WARNING|WARN|\*)\])/gi, '<span class="text-amber-400">$1</span>')
        .replace(/(\[(INFO|i)\])/gi, '<span class="text-blue-400">$1</span>')
        .replace(/(CVE-\d{4}-\d+)/g, '<span class="text-rose-300 font-medium">$1</span>')
        .replace(/(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})/g, '<span class="text-violet-300">$1</span>');
};

window.escapeAttr = function(s) {
    return String(s ?? '')
        .replace(/&/g, '&amp;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;');
};
