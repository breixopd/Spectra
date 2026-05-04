function handleDashboardSocketMessage(data) {
    try {
        const msg = JSON.parse(data);
        
        if (msg.type === 'log') {
            addTerminalLine(msg.data, 'info');
        } else if (msg.type === 'finding') {
            handleFinding(msg.data);
        } else if (msg.type === 'task_update') {
            updateTaskList(msg.data);
        } else if (msg.type === 'geo') {
            handleGeo(msg.data);
        } else if (msg.type === 'attack_surface') {
            handleAttackSurface(msg.data);
        } else if (msg.type === 'exploit_success') {
            handleExploitSuccess(msg.data);
        } else if (msg.type === 'agent_state') {
            handleAgentState(msg.data);
        } else if (msg.type === 'consensus_vote_start') {
            addTerminalLine(`[CONSENSUS] Voting on ${msg.data.risk} risk action: ${msg.data.action}`, 'warning');
        } else if (msg.type === 'consensus_vote_result') {
            const status = msg.data.status === 'approved' ? 'Approved' : 'Rejected';
            addTerminalLine(`[CONSENSUS] ${status} (Confidence: ${msg.data.average_confidence.toFixed(2)})`, msg.data.status === 'approved' ? 'success' : 'error');
        }
    } catch (e) {
        // Fallback for plain text logs
        addTerminalLine(data, 'info');
    }
}

function handleDashboardSocketMessageEvent(event) {
    handleDashboardSocketMessage(event.detail);
}

document.addEventListener('spectra:ws-message', handleDashboardSocketMessageEvent);

function handleExploitSuccess(data) {
    addTerminalLine(`Exploit confirmed: ${data.vector}`, 'success');
    
    // Refresh shell list
    updateShellList();
}

function handleAgentState(data) {
    const agentLabel = (data.agent_id || 'agent').replace(/_/g, ' ');
    if (data.status === 'running') {
        window._agentActivityLine = `${agentLabel} running…`;
    } else if (data.status === 'idle') {
        window._agentActivityLine = '';
    } else {
        window._agentActivityLine = `${agentLabel}: ${data.status}`;
        window.setTimeout(() => {
            if (window._agentActivityLine === `${agentLabel}: ${data.status}`) {
                window._agentActivityLine = '';
                const tasks = window._lastRenderedTasksForProgress;
                if (Array.isArray(tasks) && tasks.length && typeof updateMissionProgressFromTasks === 'function') {
                    updateMissionProgressFromTasks(tasks);
                }
            }
        }, 3500);
    }
    const tasks = window._lastRenderedTasksForProgress;
    if (Array.isArray(tasks) && tasks.length && typeof updateMissionProgressFromTasks === 'function') {
        updateMissionProgressFromTasks(tasks);
    } else {
        const st = document.getElementById('status-text');
        if (st && window._agentActivityLine) st.textContent = window._agentActivityLine;
    }
}
