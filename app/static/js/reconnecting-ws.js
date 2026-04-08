/**
 * ReconnectingWebSocket — wraps native WebSocket with exponential-backoff reconnect.
 */
class ReconnectingWebSocket {
    constructor(url, options = {}) {
        this.url = url;
        this.maxRetries = options.maxRetries || 10;
        this.baseDelay = options.baseDelay || 1000;
        this.maxDelay = options.maxDelay || 30000;
        this.retries = 0;
        this.handlers = { message: [], open: [], close: [], error: [] };
        this._closed = false;
        this._slowRetryTimer = null;
        // Support callbacks passed via constructor options
        if (options.onMessage) this.handlers.message.push(options.onMessage);
        if (options.onOpen) this.handlers.open.push(options.onOpen);
        if (options.onClose) this.handlers.close.push(options.onClose);
        if (options.onError) this.handlers.error.push(options.onError);
        this.connect();
    }

    connect() {
        if (this._closed) return;
        if (this._slowRetryTimer) { clearTimeout(this._slowRetryTimer); this._slowRetryTimer = null; }
        this.ws = new WebSocket(this.url);
        this.ws.onopen = (e) => {
            this.retries = 0;
            this.handlers.open.forEach(h => h(e));
        };
        this.ws.onmessage = (e) => this.handlers.message.forEach(h => h(e));
        this.ws.onclose = (e) => {
            this.handlers.close.forEach(h => h(e));
            if (!this._closed) {
                if (this.retries < this.maxRetries) {
                    const baseDelay = Math.min(this.baseDelay * Math.pow(2, this.retries), this.maxDelay);
                    const delay = Math.round(baseDelay * (0.5 + Math.random() * 0.5));
                    this.retries++;
                    console.debug(`WebSocket reconnecting in ${delay / 1000}s (attempt ${this.retries}/${this.maxRetries})`);
                    setTimeout(() => this.connect(), delay);
                } else {
                    // Slow periodic retry instead of giving up completely
                    console.debug('WebSocket max retries reached — slow retry every 60s');
                    this._slowRetryTimer = setTimeout(() => {
                        this.retries = this.maxRetries - 1;
                        this.connect();
                    }, 60000);
                }
            }
        };
        this.ws.onerror = (e) => this.handlers.error.forEach(h => h(e));
    }

    on(event, handler) { this.handlers[event].push(handler); return this; }
    send(data) { if (this.ws && this.ws.readyState === WebSocket.OPEN) this.ws.send(data); }
    close() { this._closed = true; if (this._slowRetryTimer) { clearTimeout(this._slowRetryTimer); } if (this.ws) this.ws.close(); }
    get readyState() { return this.ws ? this.ws.readyState : WebSocket.CLOSED; }
}
