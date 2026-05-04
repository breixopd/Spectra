let importFormat = 'csv';
let parsedTargets = [];

function openImportModal(fmt) {
    importFormat = fmt;
    closeImportMenu();
    clearImportPreview();
    const pasteArea = document.getElementById('import-paste-area');
    const uploadArea = document.getElementById('import-upload-area');
    const pasteInput = document.getElementById('import-paste-text');
    const fileInput = document.getElementById('import-file-input');
    if (fmt === 'paste') { pasteArea.classList.remove('hidden'); uploadArea.classList.add('hidden'); }
    else { pasteArea.classList.add('hidden'); uploadArea.classList.remove('hidden'); }
    if (pasteInput) pasteInput.value = '';
    if (fileInput) fileInput.value = '';
    const hint = document.getElementById('import-format-hint');
    hint.textContent = fmt === 'csv' ? 'CSV: ip, hostname, notes' : fmt === 'nmap' ? 'Nmap XML output file' : '';
    showSharedModal('import-modal');
}
function closeImportModal() { closeSharedModal('import-modal'); }

function handleImportDrop(e) { e.preventDefault(); const f = e.dataTransfer.files[0]; if (f) parseFile(f); }
function handleImportFile(e) { const f = e.target.files[0]; if (f) parseFile(f); }

function parseFile(file) {
    const reader = new FileReader();
    reader.onload = (e) => {
        const text = e.target.result;
        if (importFormat === 'csv') parseCSV(text);
        else if (importFormat === 'nmap') parseNmapXML(text);
        else parsePasteList(text);
    };
    reader.readAsText(file);
}

function parseCSVRows(text) {
    const rows = [];
    let currentRow = [];
    let currentField = '';
    let inQuotes = false;

    const pushRow = () => {
        currentRow.push(currentField.trim());
        if (currentRow.some((value) => value !== '')) {
            rows.push(currentRow);
        }
        currentRow = [];
        currentField = '';
    };

    for (let index = 0; index < text.length; index += 1) {
        const char = text[index];

        if (char === '"') {
            if (inQuotes && text[index + 1] === '"') {
                currentField += '"';
                index += 1;
            } else {
                inQuotes = !inQuotes;
            }
            continue;
        }

        if (char === ',' && !inQuotes) {
            currentRow.push(currentField.trim());
            currentField = '';
            continue;
        }

        if ((char === '\n' || char === '\r') && !inQuotes) {
            if (char === '\r' && text[index + 1] === '\n') {
                index += 1;
            }
            pushRow();
            continue;
        }

        currentField += char;
    }

    if (currentField !== '' || currentRow.length > 0) {
        pushRow();
    }

    return rows;
}

function parseCSV(text) {
    const rows = parseCSVRows(text);
    const hasHeader = rows[0]?.some((column) => /^(ip|address|host|hostname|notes|description)$/i.test(column));
    const data = hasHeader ? rows.slice(1) : rows;
    parsedTargets = data.map((cols) => ({
        address: cols[0] || '',
        hostname: cols[1] || '',
        notes: cols[2] || ''
    })).filter((target) => target.address);
    showPreview();
}

function parseNmapXML(text) {
    const parser = new DOMParser();
    const doc = parser.parseFromString(text, 'text/xml');
    const hosts = doc.querySelectorAll('host');
    parsedTargets = [];
    hosts.forEach(h => {
        const addrEl = h.querySelector('address');
        const addr = addrEl ? addrEl.getAttribute('addr') : null;
        if (!addr) return;
        const hostnameEl = h.querySelector('hostnames hostname');
        const hostname = hostnameEl ? hostnameEl.getAttribute('name') : '';
        const ports = [];
        h.querySelectorAll('ports port').forEach(p => {
            const state = p.querySelector('state');
            if (state && state.getAttribute('state') === 'open') ports.push(p.getAttribute('portid'));
        });
        parsedTargets.push({ address: addr, hostname, notes: ports.length ? `Ports: ${ports.join(', ')}` : '' });
    });
    showPreview();
}

function parsePasteList(text) {
    if (!text) text = document.getElementById('import-paste-text').value;
    parsedTargets = text.trim().split('\n').map(l => l.trim()).filter(Boolean).map(l => ({ address: l, hostname: '', notes: '' }));
    showPreview();
}

function showPreview() {
    if (parsedTargets.length === 0) {
        clearImportPreview();
        return;
    }

    const body = document.getElementById('import-preview-body');
    const esc = s => { const d = document.createElement('div'); d.textContent = s; return d.innerHTML; };
    body.innerHTML = parsedTargets.slice(0, 50).map(t => `<tr><td class="px-3 py-1.5 font-mono">${esc(t.address)}</td><td class="px-3 py-1.5">${esc(t.hostname)}</td><td class="px-3 py-1.5">${esc(t.notes)}</td></tr>`).join('');
    document.getElementById('import-count').textContent = parsedTargets.length;
    document.getElementById('import-preview').classList.remove('hidden');
    document.getElementById('import-btn').disabled = false;
}

function clearImportPreview() {
    parsedTargets = [];
    document.getElementById('import-preview').classList.add('hidden');
    document.getElementById('import-preview-body').innerHTML = '';
    document.getElementById('import-count').textContent = '0';
    document.getElementById('import-btn').disabled = true;
}

document.getElementById('import-paste-text')?.addEventListener('input', () => { if (importFormat === 'paste') parsePasteList(); });

async function executeImport() {
    if (parsedTargets.length === 0) return;
    document.getElementById('import-btn').disabled = true;
    document.getElementById('import-btn').innerHTML = '<i data-lucide="loader" class="w-4 h-4 inline-block animate-spin mr-2"></i>Importing...';
    if (typeof lucide !== 'undefined') lucide.createIcons();
    let success = 0;
    for (const t of parsedTargets) {
        try {
            const { data, error } = await spectraApi.post('/api/v1/targets', { address: t.address, description: t.hostname || t.notes || '', status:'pending', os:'Unknown' });
            if (!error && data) { success++; addTargetToGrid({ address: data.address, description: data.description, status: data.status, os: data.os }); }
        } catch {}
    }
    document.getElementById('import-btn').innerHTML = '<i data-lucide="file-input" class="w-4 h-4 inline-block mr-2"></i>Import All';
    if (typeof lucide !== 'undefined') lucide.createIcons();
    closeImportModal();
    if (success > 0) loadAttackSurface();
}

// Drop/dragover on import area (can't use data-action for these events)
const _importUploadArea = document.getElementById('import-upload-area');
if (_importUploadArea) {
    _importUploadArea.addEventListener('drop', e => handleImportDrop(e));
    _importUploadArea.addEventListener('dragover', e => e.preventDefault());
}

window.openImportModal = openImportModal;
window.closeImportModal = closeImportModal;
window.handleImportDrop = handleImportDrop;
window.handleImportFile = handleImportFile;
window.clearImportPreview = clearImportPreview;
window.executeImport = executeImport;
window.triggerImportFileInput = function() { document.getElementById('import-file-input').click(); };
window.navigateToTargets = function() { window.location.href = '/targets'; };
