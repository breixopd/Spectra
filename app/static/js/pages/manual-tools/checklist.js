// ========== CHECKLISTS ==========
const CHECKLIST_DATA = {
    owasp: {name:'OWASP Top 10', categories: [
        {name:'A01: Broken Access Control', items:['Test horizontal privilege escalation','Test vertical privilege escalation','Test IDOR vulnerabilities','Test missing function level access control','Check CORS misconfiguration','Test directory traversal','Verify JWT token validation']},
        {name:'A02: Cryptographic Failures', items:['Check for sensitive data in transit (TLS)','Check for weak cipher suites','Test for sensitive data exposure in URLs','Check password storage (hashing algorithm)','Test for insecure cookies (Secure/HttpOnly flags)']},
        {name:'A03: Injection', items:['Test SQL injection (all input fields)','Test NoSQL injection','Test LDAP injection','Test OS command injection','Test XSS (reflected, stored, DOM-based)','Test template injection (SSTI)','Test header injection']},
        {name:'A04: Insecure Design', items:['Review authentication flow','Test rate limiting','Check for insecure direct object references','Review business logic flaws','Test for race conditions']},
        {name:'A05: Security Misconfiguration', items:['Check default credentials','Review HTTP security headers','Test for directory listing','Check error handling (stack traces)','Review CORS policy','Test for unnecessary HTTP methods','Check for debug mode/endpoints']},
        {name:'A06: Vulnerable Components', items:['Identify all frameworks/libraries','Check for known CVEs in dependencies','Test for outdated software versions','Review third-party integrations']},
        {name:'A07: Auth Failures', items:['Test brute force protection','Test password policy enforcement','Test session management','Test multi-factor authentication bypass','Check session timeout/fixation','Test logout functionality','Test remember me functionality']},
        {name:'A08: Data Integrity', items:['Check for insecure deserialization','Verify software update mechanisms','Test CI/CD pipeline security','Check for unsigned/unverified data']},
        {name:'A09: Logging & Monitoring', items:['Verify security events are logged','Check log injection prevention','Test alerting mechanisms','Review log retention policy']},
        {name:'A10: SSRF', items:['Test for SSRF in URL parameters','Test for SSRF in file upload','Test for SSRF via webhooks','Check for internal service enumeration']},
    ]},
    network: {name:'Network Pentest', categories: [
        {name:'Reconnaissance', items:['DNS enumeration','Subdomain discovery','Port scanning (TCP full)','Port scanning (UDP top 100)','Service version detection','OS fingerprinting','SNMP enumeration','SMB enumeration']},
        {name:'Vulnerability Assessment', items:['Run Nuclei templates','Run Nessus/OpenVAS scan','Check for default credentials','Test SSL/TLS configuration','Check for known CVEs','Test for misconfigurations']},
        {name:'Exploitation', items:['Attempt default credential login','Test for known exploits (searchsploit)','Test for buffer overflows','SQL injection on web services','Test for command injection']},
        {name:'Post-Exploitation', items:['Escalate privileges','Dump credentials/hashes','Lateral movement','Persistence mechanisms','Data exfiltration paths','Clean up artifacts']},
    ]},
    api: {name:'API Security', categories: [
        {name:'Authentication', items:['Test API key security','Test OAuth flow','Test JWT implementation','Test rate limiting on auth endpoints','Test password reset flow','Check for broken authentication']},
        {name:'Authorization', items:['Test BOLA/IDOR','Test broken function level auth','Test object property level auth','Test mass assignment','Test for privilege escalation']},
        {name:'Input Validation', items:['Test for injection (SQL, NoSQL, command)','Test for XSS in API responses','Test request size limits','Test content-type validation','Test for XXE in XML parsers']},
        {name:'Data Exposure', items:['Check for excessive data exposure','Review error messages','Check for sensitive data in logs','Test for information disclosure in headers']},
    ]},
    ad: {name:'Active Directory', categories: [
        {name:'Initial Enumeration', items:['Enumerate domain controllers','Enumerate domain users','Enumerate domain groups','Enumerate GPOs','Check for null sessions','Enumerate shares','Check for AS-REP roastable accounts']},
        {name:'Credential Attacks', items:['Kerberoasting','AS-REP Roasting','Password spraying','NTLM relay','Pass the hash','Pass the ticket','Golden ticket','Silver ticket']},
        {name:'Privilege Escalation', items:['Check for misconfigured ACLs','Check for unconstrained delegation','Check for constrained delegation','Abuse GenericAll/GenericWrite','Abuse Group Policy','Check for LAPS','DCSync attack']},
        {name:'Lateral Movement', items:['PSExec','WMI execution','WinRM','DCOM execution','RDP hijacking','Named pipe impersonation']},
    ]},
    ptes: {name:'PTES', categories: [
        {name:'Pre-engagement', items:['Define scope','Get written authorization','Establish communication channels','Define rules of engagement','Emergency contacts']},
        {name:'Intelligence Gathering', items:['OSINT reconnaissance','Active DNS enumeration','Email harvesting','Technology fingerprinting','Social media review']},
        {name:'Threat Modeling', items:['Identify assets','Identify threat actors','Map attack surface','Prioritize attack vectors']},
        {name:'Vulnerability Analysis', items:['Automated scanning','Manual verification','Research public exploits','False positive elimination']},
        {name:'Exploitation', items:['Exploit identified vulnerabilities','Confirm impact','Document exploitation steps','Capture evidence']},
        {name:'Post-Exploitation', items:['Privilege escalation','Lateral movement','Data access assessment','Persistence testing']},
        {name:'Reporting', items:['Executive summary','Technical findings','Remediation recommendations','Evidence compilation']},
    ]},
};

let checklistState = {};

function loadChecklist() {
    const method = document.getElementById('checklist-methodology').value;
    const data = CHECKLIST_DATA[method];
    if (!data) return;

    const stateKey = 'spectra_checklist_' + method;
    checklistState = JSON.parse(localStorage.getItem(stateKey) || '{}');

    const container = document.getElementById('checklist-content');
    container.innerHTML = data.categories.map((cat, ci) => {
        const completed = cat.items.filter((_, ii) => checklistState[ci + '-' + ii]).length;
        return `<div class="border border-white/5 rounded-lg overflow-hidden">
            <button onclick="toggleAccordion(this)" class="w-full flex items-center justify-between px-4 py-3 bg-slate-800/50 hover:bg-slate-800 text-left transition-colors">
                <span class="text-sm font-medium text-white">${escapeHtml(cat.name)}</span>
                <span class="flex items-center gap-2">
                    <span class="text-xs text-slate-500">${completed}/${cat.items.length}</span>
                    <i data-lucide="chevron-down" class="w-3.5 h-3.5 inline-block text-slate-500 transition-transform"></i>
                </span>
            </button>
            <div class="accordion-content${ci === 0 ? ' open' : ''}">
                <div class="p-3 space-y-1">
                    ${cat.items.map((item, ii) => {
                        const key = ci + '-' + ii;
                        const checked = checklistState[key];
                        const toolMatches = item.match(/\b(nmap|nuclei|nikto|gobuster|sqlmap|hydra|searchsploit|whatweb|wpscan|feroxbuster|dirsearch|ffuf|crackmapexec|enum4linux|impacket|kerbrute|testssl)\b/gi) || [];
                        const toolBadges = toolMatches.map(t => `<button onclick="event.stopPropagation();jumpToTool('${t.toLowerCase()}')" class="px-1.5 py-0.5 bg-violet-500/10 hover:bg-violet-500/20 text-violet-400 rounded text-xs transition-colors">${t}</button>`).join('');
                        return `<div class="checklist-item ${checked ? 'completed' : ''} flex items-start gap-2 px-2 py-1.5 rounded hover:bg-white/[0.03] group">
                            <input type="checkbox" ${checked ? 'checked' : ''} onchange="toggleChecklistItem('${method}','${key}',this)" class="mt-0.5 accent-emerald-500 shrink-0">
                            <span class="checklist-text text-xs text-slate-200 flex-1">${escapeHtml(item)}</span>
                            <div class="flex gap-1 shrink-0">${toolBadges}</div>
                            <button onclick="toggleChecklistNotes(this)" class="text-slate-600 hover:text-slate-400 text-xs opacity-0 group-hover:opacity-100 transition-opacity shrink-0" title="Notes"><i data-lucide="sticky-note" class="w-3.5 h-3.5 inline-block"></i></button>
                        </div>
                        <div class="checklist-notes hidden px-8 pb-1">
                            <textarea placeholder="Notes..." rows="2" class="w-full px-2 py-1 bg-slate-900/60 border border-white/10 rounded text-[11px] text-white placeholder-slate-600 focus:outline-none resize-none" oninput="saveChecklistNote('${method}','${key}-note',this.value)">${escapeHtml(checklistState[key + '-note'] || '')}</textarea>
                        </div>`;
                    }).join('')}
                </div>
            </div>
        </div>`;
    }).join('');
    updateChecklistProgress(method);
    if (typeof lucide !== 'undefined') lucide.createIcons();
}

function toggleChecklistItem(method, key, checkbox) {
    const stateKey = 'spectra_checklist_' + method;
    checklistState[key] = checkbox.checked;
    localStorage.setItem(stateKey, JSON.stringify(checklistState));
    syncManualStateToServer();
    checkbox.closest('.checklist-item').classList.toggle('completed', checkbox.checked);
    updateChecklistProgress(method);
}

function toggleChecklistNotes(btn) {
    btn.closest('.checklist-item').nextElementSibling.classList.toggle('hidden');
}

function saveChecklistNote(method, key, value) {
    const stateKey = 'spectra_checklist_' + method;
    checklistState[key] = value;
    localStorage.setItem(stateKey, JSON.stringify(checklistState));
    syncManualStateToServer();
}

function updateChecklistProgress(method) {
    const data = CHECKLIST_DATA[method];
    if (!data) return;
    let total = 0, done = 0;
    data.categories.forEach((cat, ci) => {
        cat.items.forEach((_, ii) => {
            total++;
            if (checklistState[ci + '-' + ii]) done++;
        });
    });
    const pct = total ? Math.round((done / total) * 100) : 0;
    document.getElementById('checklist-progress-bar').style.width = pct + '%';
    document.getElementById('checklist-progress-text').textContent = `${done}/${total} completed (${pct}%)`;
}

function resetChecklist() {
    _spectraConfirm('Reset all checklist progress?', () => {
        const method = document.getElementById('checklist-methodology').value;
        checklistState = {};
        localStorage.removeItem('spectra_checklist_' + method);
        loadChecklist();
    }, { title: 'Reset Checklist' });
}

// ========== NOTES ==========
let notesData = JSON.parse(localStorage.getItem('spectra_notes') || '[]');
let activeNoteId = null;
let noteAutoSaveTimer = null;

function loadNotes() { renderNotesList(); }

function createNote() {
    const note = { id: Date.now().toString(), title: 'Untitled Note', content: '', target_id: '', finding_id: '', updated: new Date().toISOString() };
    notesData.unshift(note);
    saveNotesToStorage();
    activeNoteId = note.id;
    renderNotesList();
    showNoteEditor(note);
}

function renderNotesList() {
    const filter = document.getElementById('notes-filter')?.value || 'all';
    let filtered = notesData;
    if (filter === 'target') filtered = notesData.filter(n => n.target_id);
    if (filter === 'finding') filtered = notesData.filter(n => n.finding_id);

    const list = document.getElementById('notes-list');
    if (!filtered.length) {
        list.innerHTML = '<div class="text-slate-500 text-xs text-center py-4">No notes yet</div>';
        return;
    }
    list.innerHTML = filtered.map(n => {
        const active = n.id === activeNoteId ? 'note-item active' : '';
        const date = new Date(n.updated).toLocaleDateString([], {month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'});
        return `<div class="${active} border border-white/5 rounded-lg p-2 cursor-pointer hover:bg-white/[0.03] transition-colors" onclick="openNote('${n.id}')">
            <div class="text-xs text-white font-medium truncate">${escapeHtml(n.title || 'Untitled')}</div>
            <div class="text-xs text-slate-500">${date}</div>
        </div>`;
    }).join('');
}

function filterNotes() { renderNotesList(); }

function openNote(id) {
    const note = notesData.find(n => n.id === id);
    if (!note) return;
    activeNoteId = id;
    renderNotesList();
    showNoteEditor(note);
}

function showNoteEditor(note) {
    document.getElementById('notes-editor-empty').classList.add('hidden');
    document.getElementById('notes-editor').classList.remove('hidden');
    document.getElementById('note-title').value = note.title || '';
    document.getElementById('note-content').value = note.content || '';
    document.getElementById('note-target').value = note.target_id || '';
    document.getElementById('note-finding').value = note.finding_id || '';
    document.getElementById('note-autosave-status').textContent = '';
    // Show edit mode
    document.getElementById('note-content').classList.remove('hidden');
    document.getElementById('note-preview').classList.add('hidden');
    document.getElementById('note-preview-toggle').innerHTML = '<i data-lucide="eye" class="w-3.5 h-3.5 inline-block mr-1"></i>Preview';
}

function onNoteEdit() {
    clearTimeout(noteAutoSaveTimer);
    document.getElementById('note-autosave-status').textContent = 'Unsaved changes...';
    noteAutoSaveTimer = setTimeout(() => { saveCurrentNote(); }, 2000);
}

function saveCurrentNote() {
    if (!activeNoteId) return;
    const note = notesData.find(n => n.id === activeNoteId);
    if (!note) return;
    note.title = document.getElementById('note-title').value;
    note.content = document.getElementById('note-content').value;
    note.target_id = document.getElementById('note-target').value;
    note.finding_id = document.getElementById('note-finding').value;
    note.updated = new Date().toISOString();
    saveNotesToStorage();
    document.getElementById('note-autosave-status').textContent = 'Saved';
    renderNotesList();
}

function deleteNote() {
    if (!activeNoteId) return;
    _spectraConfirm('Delete this note?', () => {
        notesData = notesData.filter(n => n.id !== activeNoteId);
        saveNotesToStorage();
        activeNoteId = null;
        document.getElementById('notes-editor').classList.add('hidden');
        document.getElementById('notes-editor-empty').classList.remove('hidden');
        renderNotesList();
    }, { title: 'Delete Note' });
}

function saveNotesToStorage() {
    localStorage.setItem('spectra_notes', JSON.stringify(notesData));
    syncManualStateToServer();
}

function wrapNoteText(before, after) {
    const ta = document.getElementById('note-content');
    const start = ta.selectionStart, end = ta.selectionEnd;
    const text = ta.value;
    const selected = text.substring(start, end) || 'text';
    ta.value = text.substring(0, start) + before + selected + after + text.substring(end);
    ta.selectionStart = start + before.length;
    ta.selectionEnd = start + before.length + selected.length;
    ta.focus();
    onNoteEdit();
}

function toggleNotePreview() {
    const content = document.getElementById('note-content');
    const preview = document.getElementById('note-preview');
    const toggle = document.getElementById('note-preview-toggle');
    if (content.classList.contains('hidden')) {
        content.classList.remove('hidden');
        preview.classList.add('hidden');
        toggle.innerHTML = '<i data-lucide="eye" class="w-3.5 h-3.5 inline-block mr-1"></i>Preview';
    } else {
        content.classList.add('hidden');
        preview.classList.remove('hidden');
        toggle.innerHTML = '<i data-lucide="edit" class="w-3.5 h-3.5 inline-block mr-1"></i>Edit';
        preview.innerHTML = renderMarkdown(content.value);
    }
    if (typeof lucide !== 'undefined') lucide.createIcons();
}

function renderMarkdown(text) {
    return escapeHtml(text)
        .replace(/^### (.+)$/gm, '<h3 class="text-base font-bold text-white mt-2 mb-1">$1</h3>')
        .replace(/^## (.+)$/gm, '<h2 class="text-lg font-bold text-white mt-3 mb-1">$1</h2>')
        .replace(/^# (.+)$/gm, '<h1 class="text-xl font-bold text-white mt-4 mb-2">$1</h1>')
        .replace(/\*\*(.+?)\*\*/g, '<strong class="text-white">$1</strong>')
        .replace(/\*(.+?)\*/g, '<em>$1</em>')
        .replace(/`(.+?)`/g, '<code class="px-1 py-0.5 bg-black/30 rounded text-violet-300 text-xs font-mono">$1</code>')
        .replace(/\[(.+?)\]\((.+?)\)/g, '<a href="$2" class="text-violet-400 underline" target="_blank" rel="noopener noreferrer">$1</a>')
        .replace(/^- (.+)$/gm, '<li class="ml-4 list-disc">$1</li>')
        .replace(/\n/g, '<br>');
}


// ========== CVSS 3.1 CALCULATOR ==========
const cvssState = {};
const CVSS_WEIGHTS = {
    AV: {N:0.85,A:0.62,L:0.55,P:0.20},
    AC: {L:0.77,H:0.44},
    PR: {U:{N:0.85,L:0.62,H:0.27}, C:{N:0.85,L:0.68,H:0.50}},
    UI: {N:0.85,R:0.62},
    C:  {N:0,L:0.22,H:0.56},
    I:  {N:0,L:0.22,H:0.56},
    A:  {N:0,L:0.22,H:0.56},
};

function setCVSS(btn) {
    const group = btn.parentElement;
    const metric = group.dataset.cvss;
    const val = btn.dataset.val;
    group.querySelectorAll('.cvss-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    cvssState[metric] = val;
    calculateCVSS();
}

function calculateCVSS() {
    const required = ['AV','AC','PR','UI','S','C','I','A'];
    if (!required.every(m => cvssState[m])) {
        document.getElementById('cvss-score').textContent = '-';
        document.getElementById('cvss-severity').textContent = 'Select all metrics';
        document.getElementById('cvss-severity').className = 'text-sm font-bold mt-1 px-3 py-1 rounded inline-block text-slate-400';
        return;
    }

    const scopeChanged = cvssState.S === 'C';
    const av = CVSS_WEIGHTS.AV[cvssState.AV];
    const ac = CVSS_WEIGHTS.AC[cvssState.AC];
    const pr = CVSS_WEIGHTS.PR[scopeChanged ? 'C' : 'U'][cvssState.PR];
    const ui = CVSS_WEIGHTS.UI[cvssState.UI];
    const c = CVSS_WEIGHTS.C[cvssState.C];
    const i = CVSS_WEIGHTS.I[cvssState.I];
    const a = CVSS_WEIGHTS.A[cvssState.A];

    const iss = 1 - ((1 - c) * (1 - i) * (1 - a));
    let impact;
    if (scopeChanged) {
        impact = 7.52 * (iss - 0.029) - 3.25 * Math.pow(iss - 0.02, 15);
    } else {
        impact = 6.42 * iss;
    }

    if (impact <= 0) {
        updateCVSSDisplay(0);
        return;
    }

    const exploitability = 8.22 * av * ac * pr * ui;
    let score;
    if (scopeChanged) {
        score = Math.min(1.08 * (impact + exploitability), 10);
    } else {
        score = Math.min(impact + exploitability, 10);
    }
    score = Math.ceil(score * 10) / 10;
    updateCVSSDisplay(score);
}

function updateCVSSDisplay(score) {
    document.getElementById('cvss-score').textContent = score.toFixed(1);
    let severity, color, barColor;
    if (score === 0) { severity = 'NONE'; color = 'text-slate-400 bg-slate-500/10'; barColor = '#64748b'; }
    else if (score < 4) { severity = 'LOW'; color = 'text-emerald-400 bg-emerald-500/10'; barColor = '#34d399'; }
    else if (score < 7) { severity = 'MEDIUM'; color = 'text-amber-400 bg-amber-500/10'; barColor = '#fbbf24'; }
    else if (score < 9) { severity = 'HIGH'; color = 'text-orange-400 bg-orange-500/10'; barColor = '#fb923c'; }
    else { severity = 'CRITICAL'; color = 'text-rose-400 bg-rose-500/10'; barColor = '#f43f5e'; }

    document.getElementById('cvss-severity').textContent = severity;
    document.getElementById('cvss-severity').className = 'text-sm font-bold mt-1 px-3 py-1 rounded inline-block ' + color;
    document.getElementById('cvss-bar').style.width = (score * 10) + '%';
    document.getElementById('cvss-bar').style.background = barColor;

    const vector = 'CVSS:3.1/AV:' + (cvssState.AV||'?') + '/AC:' + (cvssState.AC||'?') + '/PR:' + (cvssState.PR||'?') +
        '/UI:' + (cvssState.UI||'?') + '/S:' + (cvssState.S||'?') + '/C:' + (cvssState.C||'?') + '/I:' + (cvssState.I||'?') + '/A:' + (cvssState.A||'?');
    document.getElementById('cvss-vector-display').textContent = vector;
}

function copyCVSSVector() {
    const v = document.getElementById('cvss-vector-display').textContent;
    navigator.clipboard.writeText(v);
}

function parseCVSSVector() {
    const input = document.getElementById('cvss-vector-input').value.trim();
    const match = input.match(/CVSS:3\.[01]\/AV:([NALP])\/AC:([LH])\/PR:([NLH])\/UI:([NR])\/S:([UC])\/C:([NLH])\/I:([NLH])\/A:([NLH])/);
    if (!match) { _spectraToast('Invalid CVSS vector string', 'error'); return; }
    const [, av, ac, pr, ui, s, c, i, a] = match;
    const vals = {AV:av, AC:ac, PR:pr, UI:ui, S:s, C:c, I:i, A:a};
    Object.entries(vals).forEach(([metric, val]) => {
        const group = document.querySelector(`[data-cvss="${metric}"]`);
        if (!group) return;
        group.querySelectorAll('.cvss-btn').forEach(b => {
            b.classList.toggle('active', b.dataset.val === val);
        });
        cvssState[metric] = val;
    });
    calculateCVSS();
}

