// Track safety stats
let safetyAllowed = 0;
let safetyBlocked = 0;
let safetyFlagged = 0;

function updateSafetyDisplay() {
    const el = document.getElementById('safety-stats');
    if (el) el.textContent = `${safetyAllowed} allowed / ${safetyBlocked} blocked`;
}

async function loadSafetyStats() {
    try {
        // Try dedicated safety endpoint first
        const { data, error } = await spectraApi.get('/api/v1/system/safety-stats');
        if (!error && data) {
            safetyAllowed = data.allowed || 0;
            safetyBlocked = data.blocked || 0;
            safetyFlagged = data.flagged || 0;
            updateSafetyDisplay();
            return;
        }
    } catch {}
    // Fall back to system status
    try {
        const { data, error } = await spectraApi.get('/api/v1/system/status');
        if (!error && data) {
            if (data.safety) {
                safetyAllowed = data.safety.allowed || 0;
                safetyBlocked = data.safety.blocked || 0;
                safetyFlagged = data.safety.flagged || 0;
            }
            // Also try tool_stats as a proxy for allowed commands
            if (data.tool_stats && !data.safety) {
                safetyAllowed = (data.tool_stats.total_executions || 0);
                safetyBlocked = (data.tool_stats.failed_executions || 0);
            }
            updateSafetyDisplay();
        }
    } catch {}
}

// Load safety stats on page load
loadSafetyStats();
// Auto-refresh every 30 seconds
setInterval(loadSafetyStats, 30000);

// WebSocket handler for Overseer
const originalOnMessage = window.onSocketMessage;

window.onSocketMessage = (data) => {
    // Call original handler first (for logs/toasts)
    if (originalOnMessage) originalOnMessage(data);
    
    try {
        const msg = JSON.parse(data);
        if (msg.type === 'agent_state') {
            updateAgentState(msg.data);
        } else if (msg.type === 'attack_surface') {
            updateAttackSurface(msg.data);
        } else if (msg.type === 'exploit_success') {
            showExploitSuccess(msg.data);
        } else if (msg.type === 'vector_update') {
            updateVectorStatus(msg.data);
        } else if (msg.type === 'consensus_vote_start') {
            showConsensusMonitor(msg.data);
        } else if (msg.type === 'consensus_vote_result') {
            hideConsensusMonitor(msg.data);
        } else if (msg.type === 'safety_check') {
            if (msg.data && msg.data.allowed) {
                safetyAllowed++;
            } else {
                safetyBlocked++;
            }
            updateSafetyDisplay();
        } else if (msg.type === 'tool_result') {
            // Each completed tool execution passed safety
            safetyAllowed++;
            updateSafetyDisplay();
        }
    } catch (e) {
        console.error("Overseer parse error", e);
    }
};

function updateAgentState(state) {
    const agentId = state.agent_id;
    const normalizedId = agentId.replace(/_/g, '-');
    const statusEl = document.getElementById(`status-${normalizedId}`);
    const ledEl = document.getElementById(`led-${normalizedId}`);
    
    if (statusEl) statusEl.textContent = state.status;
    
    if (ledEl) {
        ledEl.className = `w-2 h-2 rounded-full ${state.status === 'running' ? 'bg-emerald-500 animate-pulse' : 'bg-slate-700'}`;
    }
    
    // Update specific fields based on agent
    if (agentId === 'mission_controller' && state.plan) {
        document.getElementById('plan-mission-controller').textContent = state.plan;
    }
    if (agentId === 'exploit_crafter' && state.vector) {
        document.getElementById('exploit-vector').textContent = state.vector;
    }
}

function updateAttackSurface(data) {
    document.getElementById('as-services').textContent = data.services || 0;
    document.getElementById('as-domains').textContent = data.domains || 0;
    document.getElementById('as-webapps').textContent = data.web_apps || 0;
    document.getElementById('as-vulns').textContent = data.vulnerabilities || 0;
    document.getElementById('as-vectors').textContent = data.vectors_total || 0;
    
    const successRate = Math.round((data.exploitation_success_rate || 0) * 100);
    document.getElementById('as-success').textContent = successRate + '%';
    
    // Update priority counts
    if (data.vectors_by_priority) {
        document.getElementById('vectors-critical').textContent = (data.vectors_by_priority.critical || 0) + ' Critical';
        document.getElementById('vectors-high').textContent = (data.vectors_by_priority.high || 0) + ' High';
        document.getElementById('vectors-medium').textContent = (data.vectors_by_priority.medium || 0) + ' Med';
    }
}

function updateVectorStatus(data) {
    const listEl = document.getElementById('vectors-list');
    
    // Find or create vector element
    let vectorEl = document.getElementById(`vector-${data.id}`);
    if (!vectorEl) {
        vectorEl = document.createElement('div');
        vectorEl.id = `vector-${data.id}`;
        vectorEl.className = 'px-4 py-2 border-b border-white/5 flex items-center justify-between';
        listEl.appendChild(vectorEl);
        
        // Remove "no vectors" message if present
        const emptyMsg = listEl.querySelector('.text-center');
        if (emptyMsg) emptyMsg.remove();
    }
    
    const statusColors = {
        'pending': 'text-slate-400',
        'in_progress': 'text-amber-400 animate-pulse',
        'success': 'text-emerald-400',
        'failed': 'text-rose-400',
        'skipped': 'text-slate-500'
    };
    
    const priorityColors = {
        'critical': 'bg-rose-500/20 text-rose-400',
        'high': 'bg-amber-500/20 text-amber-400',
        'medium': 'bg-blue-500/20 text-blue-400',
        'low': 'bg-slate-500/20 text-slate-400'
    };
    
    vectorEl.innerHTML = `
        <div class="flex items-center space-x-3">
            <span class="px-1.5 py-0.5 rounded text-xs font-mono uppercase ${priorityColors[data.priority] || 'bg-slate-500/20'}">${escapeHtml(data.priority)}</span>
            <span class="text-sm text-white">${escapeHtml(data.name)}</span>
        </div>
        <div class="flex items-center space-x-2">
            <span class="text-xs font-mono ${statusColors[data.status] || 'text-slate-400'}">${escapeHtml(data.status)}</span>
            ${data.attempts ? `<span class="text-xs text-slate-500">(${parseInt(data.attempts, 10)}/${parseInt(data.max_attempts, 10)})</span>` : ''}
        </div>
    `;
}

function showExploitSuccess(data) {
    // Flash the exploit crafter card green
    const card = document.querySelector('#led-exploit-crafter').closest('.glass-panel');
    if (card) {
        card.classList.add('ring-2', 'ring-emerald-500');
        setTimeout(() => card.classList.remove('ring-2', 'ring-emerald-500'), 3000);
    }
    
    // Update exploit vector text
    document.getElementById('exploit-vector').textContent = `${data.vector}`;
}

function showConsensusMonitor(data) {
    const monitor = document.getElementById('consensus-monitor');
    const actionText = document.getElementById('consensus-action');
    
    actionText.textContent = `Evaluating ${data.risk} risk action: ${data.action}`;
    monitor.classList.remove('hidden');
}

function hideConsensusMonitor(data) {
    const monitor = document.getElementById('consensus-monitor');
    const actionText = document.getElementById('consensus-action');
    
    if (data.status === 'approved') {
        actionText.textContent = `Approved (Confidence: ${data.average_confidence.toFixed(2)})`;
        monitor.classList.remove('border-amber-500', 'animate-pulse');
        monitor.classList.add('border-emerald-500');
    } else {
        actionText.textContent = `Rejected: ${data.escalation_reason}`;
        monitor.classList.remove('border-amber-500', 'animate-pulse');
        monitor.classList.add('border-rose-500');
    }
    
    setTimeout(() => {
        monitor.classList.add('hidden');
        monitor.classList.remove('border-emerald-500', 'border-rose-500');
        monitor.classList.add('border-amber-500', 'animate-pulse');
    }, 5000);
}

// Fetch initial system status on page load
(async function fetchInitialState() {
    try {
        const { data, error } = await spectraApi.get('/api/v1/system/status');
        if (error || !data) return;

        // Populate agent cards from agents array if present
        if (data.agents && Array.isArray(data.agents)) {
            data.agents.forEach(agent => updateAgentState(agent));
        }

        // Populate attack surface if present
        if (data.attack_surface) {
            updateAttackSurface(data.attack_surface);
        }

        // Populate safety stats if present
        if (data.safety) {
            safetyAllowed = data.safety.allowed || 0;
            safetyBlocked = data.safety.blocked || 0;
            updateSafetyDisplay();
        }
    } catch (e) {
        console.warn('Failed to fetch initial system status:', e);
    }
})();
