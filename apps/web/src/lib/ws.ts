export type WebSocketStatus = "connecting" | "open" | "closing" | "closed" | "error";

export interface SpectraWebSocketOptions {
  protocols?: string | string[];
  onMessage?: (event: MessageEvent<string>) => void;
  onOpen?: (event: Event) => void;
  onClose?: (event: CloseEvent) => void;
  onError?: (event: Event) => void;
  reconnect?: boolean;
  reconnectDelayMs?: number;
  maxReconnectAttempts?: number;
}

export interface SpectraWebSocketHandle {
  socket: WebSocket | null;
  status: WebSocketStatus;
  connect: () => WebSocket;
  close: (code?: number, reason?: string) => void;
  send: (data: string | ArrayBufferLike | Blob | ArrayBufferView) => void;
  sendJson: (payload: unknown) => void;
}

function resolveWebSocketUrl(path: string): string {
  if (path.startsWith("ws://") || path.startsWith("wss://")) {
    return path;
  }
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  const normalized = path.startsWith("/") ? path : `/${path}`;
  return `${protocol}//${window.location.host}${normalized}`;
}

export function createSpectraWebSocket(path: string, options: SpectraWebSocketOptions = {}): SpectraWebSocketHandle {
  let socket: WebSocket | null = null;
  let status: WebSocketStatus = "closed";
  let reconnectAttempts = 0;
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  let intentionalClose = false;

  const reconnectEnabled = options.reconnect ?? false;
  const reconnectDelayMs = options.reconnectDelayMs ?? 1500;
  const maxReconnectAttempts = options.maxReconnectAttempts ?? 8;

  const setStatus = (next: WebSocketStatus) => {
    status = next;
  };

  const clearReconnectTimer = () => {
    if (reconnectTimer) {
      clearTimeout(reconnectTimer);
      reconnectTimer = null;
    }
  };

  const scheduleReconnect = () => {
    if (!reconnectEnabled || intentionalClose || reconnectAttempts >= maxReconnectAttempts) {
      return;
    }
    reconnectAttempts += 1;
    reconnectTimer = setTimeout(() => {
      connect();
    }, reconnectDelayMs);
  };

  const connect = (): WebSocket => {
    clearReconnectTimer();
    intentionalClose = false;
    setStatus("connecting");

    const url = resolveWebSocketUrl(path);
    socket = new WebSocket(url, options.protocols);
    socket.addEventListener("open", (event) => {
      setStatus("open");
      reconnectAttempts = 0;
      options.onOpen?.(event);
    });
    socket.addEventListener("message", (event) => {
      options.onMessage?.(event as MessageEvent<string>);
    });
    socket.addEventListener("close", (event) => {
      setStatus("closed");
      options.onClose?.(event);
      scheduleReconnect();
    });
    socket.addEventListener("error", (event) => {
      setStatus("error");
      options.onError?.(event);
    });
    return socket;
  };

  const close = (code?: number, reason?: string) => {
    intentionalClose = true;
    clearReconnectTimer();
    setStatus("closing");
    socket?.close(code, reason);
  };

  const send = (data: string | ArrayBufferLike | Blob | ArrayBufferView) => {
    if (!socket || socket.readyState !== WebSocket.OPEN) {
      throw new Error("WebSocket is not open");
    }
    socket.send(data);
  };

  const sendJson = (payload: unknown) => {
    send(JSON.stringify(payload));
  };

  return {
    get socket() {
      return socket;
    },
    get status() {
      return status;
    },
    connect,
    close,
    send,
    sendJson,
  };
}

/** Mission event stream — user-scoped realtime feed at `/ws`. */
export function createMissionEventsSocket(options: SpectraWebSocketOptions = {}): SpectraWebSocketHandle {
  return createSpectraWebSocket("/ws", { reconnect: true, ...options });
}

/** Interactive shell session websocket. */
export function createShellSocket(sessionId: string, options: SpectraWebSocketOptions = {}): SpectraWebSocketHandle {
  return createSpectraWebSocket(`/api/v1/shell/${sessionId}`, options);
}

export type MissionEventMessage = {
  type: string;
  [key: string]: unknown;
};

export type ShellMessage = {
  type: string;
  [key: string]: unknown;
};
