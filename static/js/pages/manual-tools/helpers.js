// === Helper Sub-Tab Switching ===
let activeHelperTab = 'revshell';
function switchHelperTab(tab) {
    activeHelperTab = tab;
    document.querySelectorAll('.helper-tab-btn').forEach(b => {
        const isActive = b.onclick && b.onclick.toString().includes("'" + tab + "'");
        if (isActive) {
            b.className = 'helper-tab-btn active px-3 py-2 text-xs font-medium text-violet-400 border-b-2 border-violet-500 whitespace-nowrap';
        } else {
            b.className = 'helper-tab-btn px-3 py-2 text-xs font-medium text-slate-400 border-b-2 border-transparent hover:text-white whitespace-nowrap';
        }
    });
    document.querySelectorAll('.helper-panel').forEach(p => p.classList.add('hidden'));
    const panel = document.getElementById('helper-' + tab);
    if (panel) panel.classList.remove('hidden');
}
