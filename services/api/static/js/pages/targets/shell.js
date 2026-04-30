let term = null;
let socket = null;
let fitAddon = null;
let shellResizeHandler = null;
let termDataDisposable = null;

function hasValidSessionId(sessionId) {
    return typeof sessionId === 'string'
        && sessionId.trim() !== ''
        && sessionId !== 'null'
        && sessionId !== 'undefined';
}

function cleanupShellResources() {
    if (termDataDisposable) {
        termDataDisposable.dispose();
        termDataDisposable = null;
    }

    if (shellResizeHandler) {
        window.removeEventListener('resize', shellResizeHandler);
        shellResizeHandler = null;
    }

    if (socket) {
        socket.close();
        socket = null;
    }

    if (term) {
        term.dispose();
        term = null;
    }

    fitAddon = null;
}

function openShell(btn, sessionId) {
    if (!hasValidSessionId(sessionId)) {
        _spectraToast('No active shell session is available for this target.', 'error');
        return;
    }

    cleanupShellResources();

    showSharedModal('shell-modal');
    document.getElementById('shell-title').textContent = `Session: ${sessionId}`;

    const container = document.getElementById('terminal-container');
    container.innerHTML = '';

    term = new Terminal({
        cursorBlink: true,
        theme: {
            background: '#000000',
            foreground: '#d4d4d4'
        }
    });

    if (typeof FitAddon !== 'undefined') {
        fitAddon = new FitAddon.FitAddon();
        term.loadAddon(fitAddon);
    }

    term.open(container);
    if (fitAddon) fitAddon.fit();

    term.writeln('\x1b[33mConnecting to shell session...\x1b[0m');

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/api/v1/shell/${sessionId}`;

    socket = new ReconnectingWebSocket(wsUrl, { maxRetries: 10 });

    socket.on('open', () => {
        if (!term) return;
        term.writeln('\x1b[32mConnected!\x1b[0m');
        term.focus();
    });

    socket.on('message', (event) => {
        if (!term) return;
        term.write(event.data);
    });

    socket.on('close', () => {
        if (!term) return;
        term.writeln('\r\n\x1b[31mConnection closed. Reconnecting...\x1b[0m');
    });

    socket.on('error', () => {
        if (!term) return;
        term.writeln('\r\n\x1b[31mConnection error.\x1b[0m');
    });

    termDataDisposable = term.onData(data => {
        socket.send(data);
    });

    shellResizeHandler = () => {
        if (fitAddon) fitAddon.fit();
    };
    window.addEventListener('resize', shellResizeHandler);
}

function closeShell() {
    closeSharedModal('shell-modal');
    cleanupShellResources();

    const container = document.getElementById('terminal-container');
    if (container) {
        container.innerHTML = '';
    }
}

window.addEventListener('pagehide', closeShell, { once: true });
window.addEventListener('beforeunload', closeShell, { once: true });

window.closeShell = closeShell;
