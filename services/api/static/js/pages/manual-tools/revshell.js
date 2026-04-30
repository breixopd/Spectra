// === Reverse Shell Generator ===
let activeShellCategory = 'all';
let selectedShellIdx = null;

function initRevShells() {
    const filterContainer = document.getElementById('revshell-cat-filters');
    filterContainer.innerHTML = SHELL_CATEGORIES.map(c =>
        `<button data-action="filterShells" data-value="${c.id}" class="revshell-cat-btn px-2 py-1 rounded text-[11px] transition-colors ${
            c.id === 'all' ? 'bg-violet-600 text-white' : 'bg-slate-800 text-slate-300 hover:bg-violet-500/10 border border-white/5'
        }" data-cat="${c.id}">${c.label}</button>`
    ).join('');
    filterShells('all');
}

function filterShells(cat) {
    activeShellCategory = cat;
    document.querySelectorAll('.revshell-cat-btn').forEach(b => {
        const isActive = b.dataset.cat === cat;
        b.className = `revshell-cat-btn px-2 py-1 rounded text-[11px] transition-colors ${isActive ? 'bg-violet-600 text-white' : 'bg-slate-800 text-slate-300 hover:bg-violet-500/10 border border-white/5'}`;
    });
    renderShellList();
}

function renderShellList() {
    const shells = activeShellCategory === 'all' ? REVERSE_SHELLS : REVERSE_SHELLS.filter(s => s.category === activeShellCategory);
    let currentCat = '';
    let html = '';
    shells.forEach((s, i) => {
        const realIdx = REVERSE_SHELLS.indexOf(s);
        if (activeShellCategory === 'all' && s.category !== currentCat) {
            currentCat = s.category;
            const catLabel = SHELL_CATEGORIES.find(c => c.id === currentCat)?.label || currentCat;
            html += `<div class="text-xs font-bold uppercase text-slate-500 mt-2 mb-1">${escapeHtml(catLabel)}</div>`;
        }
        const sel = realIdx === selectedShellIdx ? 'bg-violet-500/10 border-violet-500/30' : 'bg-white/[0.02] border-white/5 hover:bg-white/[0.05]';
        html += `<div class="flex items-center gap-2 px-2.5 py-1.5 rounded border cursor-pointer ${sel}" data-action="selectShell" data-value="${realIdx}">
            <span class="text-xs text-white font-medium">${escapeHtml(s.name)}</span>
            <span class="text-xs text-slate-500 truncate flex-1">${escapeHtml(s.description)}</span>
        </div>`;
    });
    document.getElementById('revshell-list').innerHTML = html;
}

function selectShell(idx) {
    selectedShellIdx = idx;
    renderShellList();
    genRevShell(idx);
}

function genRevShell(idx) {
    const shell = REVERSE_SHELLS[idx];
    if (!shell) return;
    const ip = document.getElementById('revshell-ip')?.value || '10.0.0.1';
    const port = document.getElementById('revshell-port')?.value || '4444';
    let output = shell.template.replace(/\{ip\}/g, ip).replace(/\{port\}/g, port);
    if (document.getElementById('revshell-b64wrap')?.checked && !['stabilize','listeners','web'].includes(shell.category)) {
        const b64 = btoa(output);
        output = `echo ${b64} | base64 -d | bash`;
    }
    document.getElementById('revshell-output').textContent = output;
    const listenerBtn = document.getElementById('revshell-copy-listener');
    if (listenerBtn) {
        listenerBtn.classList.toggle('hidden', ['stabilize','listeners','web'].includes(shell.category));
    }
}

function copyListenerCmd() {
    const port = document.getElementById('revshell-port')?.value || '4444';
    const shell = selectedShellIdx !== null ? REVERSE_SHELLS[selectedShellIdx] : null;
    let listener = `nc -lvnp ${port}`;
    if (shell) {
        if (shell.category === 'encrypted' && shell.name.includes('OpenSSL')) {
            listener = `openssl req -x509 -newkey rsa:4096 -keyout key.pem -out cert.pem -days 1 -nodes 2>/dev/null && openssl s_server -quiet -key key.pem -cert cert.pem -port ${port}`;
        } else if (shell.category === 'encrypted' && shell.name.includes('Ncat')) {
            listener = `ncat --ssl -lvnp ${port}`;
        } else if (shell.category === 'encrypted' && shell.name.includes('Socat')) {
            listener = 'socat file:`tty`,raw,echo=0 OPENSSL-LISTEN:' + port + ',reuseaddr,cert=cert.pem,key=key.pem,verify=0';
        } else if (shell.name.includes('Socat')) {
            listener = 'socat file:`tty`,raw,echo=0 TCP-L:' + port;
        }
    }
    navigator.clipboard.writeText(listener);
}
