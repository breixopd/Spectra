/**
 * Toolbox Logic
 * Handles tool listing, details, installation, and deletion.
 * Also handles Drag & Drop file uploads for plugins.
 */

let _lastToolsHash = '';

function _hashTools(tools) {
    return JSON.stringify(tools.map(t => t.id + ':' + t.status + ':' + t.name));
}

async function refreshTools() {
    const grid = document.getElementById('tools-grid');
    try {
        const { data, error } = await spectraApi.get('/api/v1/tools');
        if (error) throw new Error(error);
        const tools = data.tools || data;

        if (!tools || tools.length === 0) {
            if (_lastToolsHash !== 'empty') {
                grid.innerHTML = '<div class="empty-state glass-panel rounded-xl"><i class="fa-solid fa-toolbox text-rose-400/40"></i><h3>No tools registered</h3><p>Upload a plugin JSON file to get started.</p></div>';
                _lastToolsHash = 'empty';
            }
            return;
        }

        const newHash = _hashTools(tools);
        if (newHash === _lastToolsHash) return;
        _lastToolsHash = newHash;
        
        grid.innerHTML = tools.map((tool, i) => `
            <div onclick="selectTool('${tool.id}')" class="glass-panel p-5 rounded-xl hover:bg-white/5 cursor-pointer group border border-transparent hover:border-violet-500/30 relative overflow-hidden animate-fade-in-up" style="animation-delay: ${i * 0.04}s">
                <div class="flex justify-between items-start mb-3">
                    <div class="w-9 h-9 rounded-lg bg-violet-500/20 text-violet-400 flex items-center justify-center" style="background:${escapeHtml(tool.color || 'rgba(139,92,246,0.2)')}; color:#fff;">
                        <i class="fa-solid ${escapeHtml(tool.icon || 'fa-wrench')}"></i>
                    </div>
                    <span class="px-2 py-0.5 rounded text-[10px] font-mono font-medium ${getStatusColor(tool.status)}">
                        ${(tool.status || 'pending').toUpperCase()}
                    </span>
                </div>
                <h3 class="text-white font-semibold mb-1">${escapeHtml(tool.name)}</h3>
                <p class="text-slate-400 text-xs line-clamp-2">${escapeHtml(tool.description)}</p>
                <div class="mt-2 text-[10px] text-slate-500 font-mono">${escapeHtml(tool.category)} · v${escapeHtml(tool.version)}</div>
            </div>
        `).join('');
    } catch (e) {
        grid.innerHTML = `<div class="text-red-400 p-4">Failed to load tools: ${escapeHtml(String(e))}</div>`;
    }
}

function getStatusColor(status) {
    const map = {
        'ready': 'bg-green-500/20 text-green-400',
        'installing': 'bg-blue-500/20 text-blue-400 animate-pulse',
        'failed': 'bg-red-500/20 text-red-400',
        'pending': 'bg-yellow-500/20 text-yellow-400',
        'disabled': 'bg-slate-500/20 text-slate-400'
    };
    return map[status] || 'bg-gray-500/20 text-gray-400';
}

let currentTool = null;

async function selectTool(id) {
    const container = document.getElementById('tool-details');
    container.innerHTML = '<div class="text-center py-8 text-slate-500"><i class="fa-solid fa-spinner fa-spin mr-2"></i>Loading...</div>';
    
    try {
        const [toolResult, statsResult] = await Promise.all([
            spectraApi.get(`/api/v1/tools/${id}`),
            spectraApi.get(`/api/v1/tools/${id}/stats`)
        ]);
        const tool = toolResult.data;
        const stats = statsResult.data;
        currentTool = tool;
        
        const successRate = stats.total_count > 0
            ? Math.round((stats.success_count / stats.total_count) * 100)
            : 0;

        container.innerHTML = `
            <div class="flex items-center gap-4 mb-6 animate-fade-in-up">
                <div class="w-12 h-12 rounded-xl flex items-center justify-center text-xl" style="background:${escapeHtml(tool.color || 'rgba(139,92,246,0.2)')}; color:#fff;">
                    <i class="fa-solid ${escapeHtml(tool.icon || 'fa-wrench')}"></i>
                </div>
                <div>
                    <h2 class="text-xl font-bold text-white">${escapeHtml(tool.name)}</h2>
                    <p class="text-slate-400 text-sm">v${escapeHtml(tool.version)} · ${escapeHtml(tool.category)}</p>
                </div>
            </div>
            
            <div class="grid grid-cols-3 gap-3 mb-4 animate-fade-in-up stagger-1">
                <div class="bg-black/30 rounded-lg p-3 text-center">
                    <div class="text-2xl font-bold font-mono text-white">${stats.total_count || 0}</div>
                    <div class="text-[10px] text-slate-500 uppercase">Runs</div>
                </div>
                <div class="bg-black/30 rounded-lg p-3 text-center">
                    <div class="text-2xl font-bold font-mono text-emerald-400">${stats.success_count || 0}</div>
                    <div class="text-[10px] text-slate-500 uppercase">Pass</div>
                </div>
                <div class="bg-black/30 rounded-lg p-3 text-center">
                    <div class="text-2xl font-bold font-mono text-rose-400">${stats.fail_count || 0}</div>
                    <div class="text-[10px] text-slate-500 uppercase">Fail</div>
                </div>
            </div>

            ${stats.total_count > 0 ? `
            <div class="mb-4">
                <div class="flex justify-between text-xs text-slate-500 mb-1"><span>Success Rate</span><span>${successRate}%</span></div>
                <div class="h-1.5 bg-black/30 rounded-full overflow-hidden">
                    <div class="h-full bg-gradient-to-r from-emerald-500 to-emerald-400 transition-all duration-500" style="width: ${successRate}%"></div>
                </div>
            </div>` : ''}
            
            <div class="space-y-4 animate-fade-in-up stagger-2">
                <div>
                    <label class="text-[10px] font-bold text-slate-500 uppercase tracking-wider">Description</label>
                    <p class="text-slate-300 text-sm mt-1">${escapeHtml(tool.description)}</p>
                </div>
                <div>
                    <label class="text-[10px] font-bold text-slate-500 uppercase tracking-wider">Command</label>
                    <code class="block mt-1 p-3 rounded-lg bg-black/40 font-mono text-xs text-violet-300 overflow-x-auto">${escapeHtml(tool.execution_command)} ${escapeHtml(tool.args_template)}</code>
                </div>
                ${tool.status_message || (tool.install_logs && tool.install_logs.length) ? `
                <div>
                    <label class="text-[10px] font-bold text-slate-500 uppercase tracking-wider">Install Status</label>
                    <div class="mt-1 p-3 rounded-lg bg-black/40 border border-white/5">
                        <div class="text-xs text-slate-300">${escapeHtml(tool.status_message || tool.status_phase || 'No additional status')}</div>
                        ${tool.last_updated ? `<div class="text-[10px] text-slate-500 mt-1">Updated: ${escapeHtml(tool.last_updated)}</div>` : ''}
                        ${tool.last_output ? `<pre class="text-[11px] text-slate-400 mt-2 whitespace-pre-wrap">${escapeHtml(tool.last_output)}</pre>` : ''}
                        ${tool.install_logs && tool.install_logs.length ? `<div class="mt-2 max-h-40 overflow-y-auto rounded bg-black/30 p-2 text-[11px] text-slate-400 whitespace-pre-wrap">${tool.install_logs.map(line => escapeHtml(line)).join('\n')}</div>` : ''}
                    </div>
                </div>` : ''}
                <div class="pt-4 border-t border-white/10 flex gap-3">
                    <button onclick="showTestModal('${tool.id}')" class="flex-1 py-2.5 rounded-lg bg-violet-600 hover:bg-violet-500 active:scale-[0.98] text-white text-sm font-medium transition-all">
                        <i class="fa-solid fa-play mr-1"></i> Run Test
                    </button>
                    ${tool.enabled ? `
                        <button onclick="toggleToolEnabled('${tool.id}', false)" class="px-4 py-2.5 rounded-lg bg-slate-500/10 hover:bg-slate-500/20 text-slate-300 transition-colors">
                            <i class="fa-solid fa-toggle-off"></i>
                        </button>
                    ` : `
                        <button onclick="toggleToolEnabled('${tool.id}', true)" class="px-4 py-2.5 rounded-lg bg-amber-500/10 hover:bg-amber-500/20 text-amber-400 transition-colors">
                            <i class="fa-solid fa-toggle-on"></i>
                        </button>
                    `}
                    ${tool.status !== 'ready' && tool.status !== 'installing' ? `
                        <button onclick="installTool('${tool.id}')" class="flex-1 py-2.5 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white text-sm font-medium transition-colors">
                            <i class="fa-solid fa-download mr-1"></i> Install
                        </button>
                    ` : ''}
                    <button onclick="deleteTool('${tool.id}')" class="px-4 py-2.5 rounded-lg bg-rose-500/10 hover:bg-rose-500/20 text-rose-400 transition-colors">
                        <i class="fa-solid fa-trash"></i>
                    </button>
                </div>
            </div>
        `;
    } catch (e) {
        container.innerHTML = `<div class="text-red-400 p-4">Error: ${escapeHtml(String(e))}</div>`;
    }
}

async function installTool(id) {
    const logs = document.getElementById('install-logs');
    logs.innerHTML += `\n> Requesting installation for ${id}...`;
    
    try {
        const { error } = await spectraApi.post(`/api/v1/tools/${id}/install`);
        if (error) throw new Error(error);
        
        logs.innerHTML += `\n> Installation started.`;
        refreshTools();
        selectTool(id);
    } catch (e) {
        logs.innerHTML += `\n> Error: ${e.message}`;
    }
}

async function toggleToolEnabled(id, enabled) {
    const logs = document.getElementById('install-logs');
    logs.innerHTML += `\n> ${enabled ? 'Enabling' : 'Disabling'} ${id}...`;

    try {
        const path = enabled ? 'enable' : 'disable';
        const { error } = await spectraApi.post(`/api/v1/tools/${id}/${path}`);
        if (error) throw new Error(error);
        logs.innerHTML += `\n> ${enabled ? 'Enabled' : 'Disabled'} ${id}.`;
        await refreshTools();
        await selectTool(id);
    } catch (e) {
        logs.innerHTML += `\n> Error: ${e.message}`;
    }
}

async function deleteTool(id) {
    if (!confirm('Are you sure you want to delete this tool?')) return;
    
    try {
        await spectraApi.delete(`/api/v1/tools/${id}`);
        refreshTools();
        document.getElementById('tool-details').innerHTML = '<p class="text-gray-500 italic text-center mt-10">Select a tool to view details</p>';
    } catch (e) {
        alert(e);
    }
}

// Drag & Drop Logic
document.addEventListener('DOMContentLoaded', () => {
    const dropZone = document.getElementById('drop-zone');
    const fileInput = document.getElementById('file-input');
    
    if (dropZone && fileInput) {
        dropZone.onclick = () => fileInput.click();
        
        dropZone.ondragover = (e) => {
            e.preventDefault();
            dropZone.classList.add('border-violet-500', 'bg-violet-500/10');
        };
        
        dropZone.ondragleave = () => {
            dropZone.classList.remove('border-violet-500', 'bg-violet-500/10');
        };
        
        dropZone.ondrop = (e) => {
            e.preventDefault();
            dropZone.classList.remove('border-violet-500', 'bg-violet-500/10');
            handleFiles(e.dataTransfer.files);
        };
        
        fileInput.onchange = () => handleFiles(fileInput.files);
    }

    // Initial load
    refreshTools();
    
    // Poll for updates
    setInterval(refreshTools, 5000);
});

async function handleFiles(files) {
    if (files.length === 0) return;
    const file = files[0];
    
    const status = document.getElementById('upload-status');
    status.classList.remove('hidden');
    status.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Uploading...';
    
    try {
        // [FIX] Use FormData to send file, not JSON
        const formData = new FormData();
        formData.append('file', file);

        const { error } = await spectraApi.request('/api/v1/tools/upload', {
            method: 'POST',
            body: formData
        });
        
        if (error) throw new Error(error);
        
        status.innerHTML = '<span class="text-green-400">Upload successful!</span>';
        setTimeout(() => {
            document.getElementById('upload-modal').classList.add('hidden');
            status.classList.add('hidden');
            refreshTools();
        }, 1000);
        
    } catch (e) {
        status.innerHTML = `<span class="text-red-400">Error: ${escapeHtml(e.message)}</span>`;
    }
}

// Tool Test Functions
function showTestModal(toolId) {
    const modal = document.getElementById('test-modal');
    if (!modal) {
        // Create modal if it doesn't exist
        document.body.insertAdjacentHTML('beforeend', `
            <div id="test-modal" class="fixed inset-0 bg-black/80 backdrop-blur-sm z-50 flex items-center justify-center">
                <div class="glass p-8 rounded-2xl w-full max-w-2xl relative max-h-[80vh] overflow-hidden flex flex-col">
                    <button onclick="document.getElementById('test-modal').remove()" class="absolute top-4 right-4 text-gray-400 hover:text-white">
                        <i class="fa-solid fa-xmark text-xl"></i>
                    </button>
                    
                    <h3 class="text-xl font-bold text-white mb-4">Test Tool: <span id="test-tool-name">${toolId}</span></h3>
                    
                    <div class="space-y-4 mb-4">
                        <div>
                            <label class="text-xs font-bold text-gray-500 uppercase">Target</label>
                            <input id="test-target" type="text" placeholder="e.g., 192.168.1.1 or example.com" 
                                   class="w-full mt-1 p-3 rounded-lg bg-black/50 border border-gray-700 text-white focus:border-violet-500 focus:outline-none">
                        </div>
                        <div>
                            <label class="text-xs font-bold text-gray-500 uppercase">Additional Args (JSON)</label>
                            <input id="test-args" type="text" placeholder='e.g., {"ports": "80,443"}' 
                                   class="w-full mt-1 p-3 rounded-lg bg-black/50 border border-gray-700 text-white focus:border-violet-500 focus:outline-none">
                        </div>
                    </div>
                    
                    <button onclick="runToolTest('${toolId}')" id="test-run-btn" class="w-full py-3 rounded-lg bg-violet-600 hover:bg-violet-500 text-white font-medium transition-colors mb-4">
                        <i class="fa-solid fa-play"></i> Run Test
                    </button>
                    
                    <div id="test-result" class="flex-1 overflow-auto bg-black/50 rounded-lg p-4 font-mono text-sm hidden">
                    </div>
                </div>
            </div>
        `);
    } else {
        modal.classList.remove('hidden');
        document.getElementById('test-tool-name').textContent = toolId;
    }
}

async function runToolTest(toolId) {
    const target = document.getElementById('test-target').value;
    const argsInput = document.getElementById('test-args').value;
    const resultDiv = document.getElementById('test-result');
    const runBtn = document.getElementById('test-run-btn');

    if (!target) {
        alert('Please enter a target');
        return;
    }

    let args = {};
    if (argsInput) {
        try {
            args = JSON.parse(argsInput);
        } catch (e) {
            alert('Invalid JSON in args field');
            return;
        }
    }

    runBtn.disabled = true;
        runBtn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Running...';
    resultDiv.classList.remove('hidden');
    resultDiv.innerHTML = '<div class="text-gray-400">Executing tool... This may take a while.</div>';

    try {
        const { data: result, error: testError } = await spectraApi.post(`/api/v1/tools/${toolId}/test`, { target, args });
        if (testError) throw new Error(testError);

        if (result.success) {
            resultDiv.innerHTML = `
                <div class="text-green-400 mb-2">[SUCCESS] Exit code: ${result.exit_code} | Duration: ${result.duration_seconds?.toFixed(2)}s</div>
                <div class="text-gray-300 mb-2">Parsed Findings: ${result.parsed_findings_count}</div>
                ${result.parsed_findings?.length > 0 ? `
                    <div class="text-violet-400 mb-2">Sample Findings:</div>
                    <pre class="text-xs text-gray-400 overflow-x-auto">${escapeHtml(JSON.stringify(result.parsed_findings.slice(0, 5), null, 2))}</pre>
                ` : ''}
                <div class="text-gray-500 mt-4 border-t border-gray-700 pt-2">STDOUT (truncated):</div>
                <pre class="text-xs text-gray-400 overflow-x-auto whitespace-pre-wrap max-h-48">${escapeHtml(result.stdout?.slice(0, 2000) || '(empty)')}</pre>
                ${result.stderr ? `
                    <div class="text-yellow-500 mt-2">STDERR:</div>
                    <pre class="text-xs text-yellow-400/70 overflow-x-auto whitespace-pre-wrap">${escapeHtml(result.stderr)}</pre>
                ` : ''}
            `;
        } else {
            resultDiv.innerHTML = `
                <div class="text-red-400 mb-2">[FAILED] Exit code: ${result.exit_code}</div>
                <div class="text-gray-500 mt-2">STDOUT:</div>
                <pre class="text-xs text-gray-400 overflow-x-auto whitespace-pre-wrap">${escapeHtml(result.stdout || '(empty)')}</pre>
                <div class="text-red-500 mt-2">STDERR:</div>
                <pre class="text-xs text-red-400/70 overflow-x-auto whitespace-pre-wrap">${escapeHtml(result.stderr || '(empty)')}</pre>
            `;
        }
    } catch (e) {
        resultDiv.innerHTML = `<div class="text-red-400">Error: ${escapeHtml(e.message)}</div>`;
    } finally {
        runBtn.disabled = false;
        runBtn.innerHTML = '<i class="fa-solid fa-play"></i> Run Test';
    }
}

// escapeHtml is provided globally by api.js (window.escapeHtml)
