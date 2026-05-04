// ========== COMMAND HISTORY ==========
let commandHistory = JSON.parse(localStorage.getItem('spectra_cmd_history') || '[]');
let historySortKey = 'time';
let historySortAsc = false;

function addToHistory(entry) {
    commandHistory.unshift(entry);
    if (commandHistory.length > 200) commandHistory.pop();
    localStorage.setItem('spectra_cmd_history', JSON.stringify(commandHistory));
    syncManualStateToServer();
    renderHistory();
}

function renderHistory() {
    const search = (document.getElementById('history-search')?.value || '').toLowerCase();
    const toolFilter = document.getElementById('history-tool-filter')?.value || '';

    // Populate tool filter dropdown
    const toolSelect = document.getElementById('history-tool-filter');
    const tools = [...new Set(commandHistory.map(h => h.tool))];
    const currentVal = toolSelect.value;
    toolSelect.innerHTML = '<option value="">All tools</option>' + tools.map(t => `<option value="${escapeAttr(t)}">${escapeHtml(t)}</option>`).join('');
    toolSelect.value = currentVal;

    let filtered = commandHistory.filter(h => {
        if (toolFilter && h.tool !== toolFilter) return false;
        if (search && !h.tool.toLowerCase().includes(search) && !h.target.toLowerCase().includes(search) && !(h.output||'').toLowerCase().includes(search)) return false;
        return true;
    });

    // Sort
    filtered.sort((a, b) => {
        let va, vb;
        if (historySortKey === 'time') { va = new Date(a.time); vb = new Date(b.time); }
        else if (historySortKey === 'tool') { va = a.tool; vb = b.tool; }
        else if (historySortKey === 'status') { va = a.status ? 1 : 0; vb = b.status ? 1 : 0; }
        else if (historySortKey === 'duration') { va = a.duration; vb = b.duration; }
        else { va = a[historySortKey]; vb = b[historySortKey]; }
        if (va < vb) return historySortAsc ? -1 : 1;
        if (va > vb) return historySortAsc ? 1 : -1;
        return 0;
    });

    document.getElementById('history-list').innerHTML = filtered.slice(0, 50).map((h, i) => {
        const t = new Date(h.time);
        const timeStr = t.toLocaleTimeString([], {hour:'2-digit',minute:'2-digit',second:'2-digit'});
        const statusIcon = h.status ? '<span class="text-emerald-400">&#10003;</span>' : '<span class="text-rose-400">&#10007;</span>';
        const dur = h.duration ? h.duration.toFixed(1) + 's' : '-';
        return `<tr class="border-b border-white/[0.03] hover:bg-white/[0.03] text-xs">
            <td class="px-3 py-1.5 text-slate-400 font-mono">${timeStr}</td>
            <td class="px-3 py-1.5 text-violet-400">${escapeHtml(h.tool)}</td>
            <td class="px-3 py-1.5 text-white font-mono truncate max-w-[150px]">${escapeHtml(h.target)}</td>
            <td class="px-3 py-1.5">${statusIcon}</td>
            <td class="px-3 py-1.5 text-slate-400 font-mono">${dur}</td>
            <td class="px-3 py-1.5 text-right">
                <button data-action="viewHistoryOutput" data-value="${i}" class="px-1.5 py-0.5 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded text-xs transition-colors mr-1">View</button>
                <button data-action="rerunFromHistory" data-value="${i}" class="px-1.5 py-0.5 bg-violet-600/60 hover:bg-violet-500 text-white rounded text-xs transition-colors">Re-run</button>
            </td>
        </tr>`;
    }).join('') || '<tr><td colspan="6" class="px-3 py-4 text-center text-slate-500 text-xs">No history yet</td></tr>';
}

function sortHistory(key) {
    if (historySortKey === key) historySortAsc = !historySortAsc;
    else { historySortKey = key; historySortAsc = true; }
    renderHistory();
}

function filterHistory() { renderHistory(); }

function toggleHistoryPanel() {
    const panel = document.getElementById('history-panel');
    const chevron = document.getElementById('history-chevron');
    panel.classList.toggle('hidden');
    chevron.classList.toggle('rotate-180');
    if (!panel.classList.contains('hidden')) renderHistory();
}

function viewHistoryOutput(idx) {
    const h = commandHistory[idx];
    if (!h) return;
    showSpectraModal('Output: ' + h.tool + ' → ' + h.target, `<pre class="text-xs text-slate-300 font-mono whitespace-pre-wrap p-4 max-h-[60vh] overflow-y-auto">${colorizeOutput(escapeHtml(h.output || '(no output)'))}</pre>` +
        (h.stderr ? `<pre class="text-xs text-amber-500/70 font-mono whitespace-pre-wrap p-4 border-t border-white/5">${escapeHtml(h.stderr)}</pre>` : ''));
}

function rerunFromHistory(idx) {
    const h = commandHistory[idx];
    if (!h) return;
    switchManualTab('execute');
    selectManualTool(h.toolId || h.tool.toLowerCase());
    setTimeout(() => {
        const targetInput = document.getElementById('arg-target');
        if (targetInput) targetInput.value = h.target;
        executeManualTool();
    }, 400);
}

// ========== DIFF MODAL ==========
function openDiffModal() {
    if (commandHistory.length < 2) { showToast('Need at least 2 command runs to compare', 'warning'); return; }
    const options = commandHistory.slice(0, 50).map((h, i) => {
        const t = new Date(h.time).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit',second:'2-digit'});
        return `<option value="${i}">${t} - ${h.tool} → ${h.target}</option>`;
    }).join('');

    showSpectraModal('Compare Outputs', `
        <div class="p-4">
            <div class="flex gap-4 mb-4">
                <div class="flex-1"><label class="text-xs text-slate-500 uppercase font-bold">Left</label>
                    <select id="diff-left" class="w-full px-2 py-1.5 bg-slate-900/60 border border-white/10 rounded text-xs text-white focus:outline-none">${options}</select></div>
                <div class="flex-1"><label class="text-xs text-slate-500 uppercase font-bold">Right</label>
                    <select id="diff-right" class="w-full px-2 py-1.5 bg-slate-900/60 border border-white/10 rounded text-xs text-white focus:outline-none"><option value="1" selected>${commandHistory.length > 1 ? '' : ''}</option>${options}</select></div>
            </div>
            <button data-action="runDiff" class="px-4 py-2 bg-violet-600 hover:bg-violet-500 text-white rounded text-xs mb-3">Compare</button>
            <div id="diff-output" class="flex gap-2 max-h-[50vh] overflow-y-auto"></div>
        </div>`, 'max-w-5xl');
    if (commandHistory.length > 1) document.getElementById('diff-right').value = '1';
}

function runDiff() {
    const leftIdx = parseInt(document.getElementById('diff-left').value);
    const rightIdx = parseInt(document.getElementById('diff-right').value);
    const left = (commandHistory[leftIdx]?.output || '').split('\n');
    const right = (commandHistory[rightIdx]?.output || '').split('\n');

    const maxLen = Math.max(left.length, right.length);
    let leftHtml = '', rightHtml = '';
    for (let i = 0; i < maxLen; i++) {
        const l = left[i] || '';
        const r = right[i] || '';
        if (l === r) {
            leftHtml += `<div class="diff-unchanged px-2">${escapeHtml(l)}</div>`;
            rightHtml += `<div class="diff-unchanged px-2">${escapeHtml(r)}</div>`;
        } else {
            leftHtml += `<div class="diff-del px-2">${l ? '-' + escapeHtml(l) : '&nbsp;'}</div>`;
            rightHtml += `<div class="diff-add px-2">${r ? '+' + escapeHtml(r) : '&nbsp;'}</div>`;
        }
    }
    document.getElementById('diff-output').innerHTML = `
        <div class="flex-1 bg-black rounded-lg overflow-auto font-mono text-[11px] leading-5 p-2">${leftHtml}</div>
        <div class="flex-1 bg-black rounded-lg overflow-auto font-mono text-[11px] leading-5 p-2">${rightHtml}</div>`;
}
