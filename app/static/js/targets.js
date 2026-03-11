// Targets Management Logic

function openAddTargetModal() {
    document.getElementById('add-target-modal').classList.remove('hidden');
}

function closeAddTargetModal() {
    document.getElementById('add-target-modal').classList.add('hidden');
}

async function handleAddTarget(event) {
    event.preventDefault();
    const formData = new FormData(event.target);
    const data = Object.fromEntries(formData.entries());
    
    try {
        const { data: target, error } = await spectraApi.post('/api/v1/targets', {
            address: data.address,
            description: data.description,
            status: 'pending',
            os: 'Unknown'
        });
        
        if (!error) {
            
            // Add to grid
            addTargetToGrid({
                address: target.address,
                description: target.description,
                status: target.status,
                os: target.os,
                ports: 'None'
            });
            
            closeAddTargetModal();
            event.target.reset();
        } else {
            alert(`Failed to add target: ${error}`);
        }
    } catch (error) {
        console.error('Error adding target:', error);
        alert('Error adding target');
    }
}

function addTargetToGrid(target) {
    const grid = document.getElementById('targets-grid');
    const template = document.getElementById('target-card-template');
    const clone = template.content.cloneNode(true);
    
    clone.querySelector('.target-name').textContent = target.address;
    clone.querySelector('.target-desc').textContent = target.description || 'No description';
    
    // Pass session ID if available (assuming target object has session info)
    const sessionId = target.session_id || null;
    const shellBtn = clone.querySelector('.shell-btn');
    if (shellBtn) {
        shellBtn.onclick = () => openShell(shellBtn, sessionId);
        if (!sessionId) {
            shellBtn.classList.add('opacity-50', 'cursor-not-allowed');
            shellBtn.title = "No active shell session";
        }
    }

    grid.appendChild(clone);
}

// --- Shell Handler ---

let term = null;
let socket = null;
let fitAddon = null;

function openShell(btn, sessionId) {
    document.getElementById('shell-modal').classList.remove('hidden');
    document.getElementById('shell-title').textContent = sessionId ? `Session: ${sessionId}` : 'Connecting...';

    // Initialize xterm.js
    const container = document.getElementById('terminal-container');
    container.innerHTML = ''; // Clear previous

    term = new Terminal({
        cursorBlink: true,
        theme: {
            background: '#000000',
            foreground: '#d4d4d4'
        }
    });

    // Load Fit Addon if available (from CDN in HTML)
    if (typeof FitAddon !== 'undefined') {
        fitAddon = new FitAddon.FitAddon();
        term.loadAddon(fitAddon);
    }

    term.open(container);
    if (fitAddon) fitAddon.fit();

    term.writeln('\x1b[33mConnecting to shell session...\x1b[0m');

    // Connect WebSocket
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/api/v1/shell/${sessionId}`;

    socket = new WebSocket(wsUrl);

    socket.onopen = () => {
        term.writeln('\x1b[32mConnected!\x1b[0m');
        term.focus();
    };

    socket.onmessage = (event) => {
        term.write(event.data);
    };

    socket.onclose = () => {
        term.writeln('\r\n\x1b[31mConnection closed.\x1b[0m');
    };

    socket.onerror = (error) => {
        term.writeln('\r\n\x1b[31mConnection error.\x1b[0m');
    };

    // Send input to server
    term.onData(data => {
        if (socket && socket.readyState === WebSocket.OPEN) {
            socket.send(data);
        }
    });

    // Handle resize
    window.addEventListener('resize', () => {
        if (fitAddon) fitAddon.fit();
    });
}

function closeShell() {
    document.getElementById('shell-modal').classList.add('hidden');
    if (socket) {
        socket.close();
        socket = null;
    }
    if (term) {
        term.dispose();
        term = null;
    }
}

// Initialize with some dummy data
document.addEventListener('DOMContentLoaded', () => {
    // These calls are placeholders. In a real scenario, fetch from API.
    // addTargetToGrid(...)
});
