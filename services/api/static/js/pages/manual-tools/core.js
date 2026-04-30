// Shared state for manual-tools modules
let allTools = [];
let selectedToolId = null;
let selectedToolConfig = null;
let pipelineSteps = [];
let pipelineStepId = 0;
let lastToolOutput = '';
let allFindings = [];
let lastParsedFindings = [];

// Tab switching — delegates to tabs.js module; kept as a function because it is
// called programmatically from within this file (e.g. after CVE lookup, pipeline run).
function switchManualTab(tab) {
    if (window.activateTab) {
        window.activateTab('manual-tabs', tab);
    }
}

// Tool chaining suggestions
const TOOL_CHAINS = {
    nmap: ['nuclei', 'nikto', 'searchsploit', 'gobuster'],
    nuclei: ['searchsploit', 'sqlmap', 'nikto'],
    nikto: ['sqlmap', 'gobuster', 'dirsearch'],
    whatweb: ['nikto', 'nuclei', 'wpscan'],
    gobuster: ['nikto', 'sqlmap', 'ffuf'],
    dirsearch: ['nikto', 'sqlmap', 'ffuf'],
    subfinder: ['nmap', 'httpx', 'nuclei'],
    httpx: ['nuclei', 'nikto', 'gobuster'],
    wpscan: ['sqlmap', 'nuclei'],
    naabu: ['nmap', 'nuclei', 'httpx'],
    feroxbuster: ['nikto', 'sqlmap'],
};

function escapeAttr(s) { return s.replace(/'/g, "\\'").replace(/"/g, '&quot;'); }

function colorizeOutput(text) {
    return text
        .replace(/(\[(\+|SUCCESS|FOUND|open)\])/gi, '<span class="text-emerald-400">$1</span>')
        .replace(/(\[(-|FAIL|ERROR|closed)\])/gi, '<span class="text-rose-400">$1</span>')
        .replace(/(\[(WARNING|WARN|\*)\])/gi, '<span class="text-amber-400">$1</span>')
        .replace(/(\[(INFO|i)\])/gi, '<span class="text-blue-400">$1</span>')
        .replace(/(CVE-\d{4}-\d+)/g, '<span class="text-rose-300 font-medium">$1</span>')
        .replace(/(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})/g, '<span class="text-violet-300">$1</span>');
}

function showSpectraModal(title, content, widthClass) {
    const existing = document.getElementById('spectra-modal');
    if (existing) existing.remove();
    const modal = document.createElement('div');
    modal.id = 'spectra-modal';
    modal.className = 'modal-overlay';
    modal.onclick = (e) => { if (e.target === modal) modal.remove(); };
    modal.innerHTML = `<div class="modal-content ${widthClass || 'max-w-3xl'} w-full">
        <div class="flex items-center justify-between px-4 py-3 border-b border-white/10">
            <h3 class="text-sm font-bold text-white">${escapeHtml(title)}</h3>
            <button  data-action="closeSpectraModal" class="text-slate-400 hover:text-white"><i data-lucide="x" class="w-3.5 h-3.5 inline-block"></i></button>
        </div>
        <div>${content}</div>
    </div>`;
    document.body.appendChild(modal);
}
