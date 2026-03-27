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
        this.connect();
    }

    connect() {
        if (this._closed) return;
        this.ws = new WebSocket(this.url);
        this.ws.onopen = (e) => {
            this.retries = 0;
            this.handlers.open.forEach(h => h(e));
        };
        this.ws.onmessage = (e) => this.handlers.message.forEach(h => h(e));
        this.ws.onclose = (e) => {
            this.handlers.close.forEach(h => h(e));
            if (!this._closed && this.retries < this.maxRetries) {
                const delay = Math.min(this.baseDelay * Math.pow(2, this.retries), this.maxDelay);
                this.retries++;
                console.debug(`WebSocket reconnecting in ${delay / 1000}s (attempt ${this.retries}/${this.maxRetries})`);
                setTimeout(() => this.connect(), delay);
            }
        };
        this.ws.onerror = (e) => this.handlers.error.forEach(h => h(e));
    }

    on(event, handler) { this.handlers[event].push(handler); return this; }
    send(data) { if (this.ws && this.ws.readyState === WebSocket.OPEN) this.ws.send(data); }
    close() { this._closed = true; if (this.ws) this.ws.close(); }
    get readyState() { return this.ws ? this.ws.readyState : WebSocket.CLOSED; }
}
