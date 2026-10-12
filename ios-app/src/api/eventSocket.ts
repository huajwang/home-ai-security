import { HubClient } from './hubClient';

export type EventCallback = (event: any) => void;
export type StatusCallback = (connected: boolean) => void;

export class EventSocket {
  private socket: WebSocket | null = null;
  private pingInterval: any = null;
  private reconnectTimeout: any = null;
  private isClosedManually = false;
  private onEventCallback: EventCallback | null = null;
  private onStatusCallback: StatusCallback | null = null;

  constructor(onEvent?: EventCallback, onStatus?: StatusCallback) {
    if (onEvent) this.onEventCallback = onEvent;
    if (onStatus) this.onStatusCallback = onStatus;
  }

  public async connect(): Promise<void> {
    this.isClosedManually = false;
    this.cleanup();

    try {
      const wsUrl = await HubClient.getWsUrl();
      const ws = new WebSocket(wsUrl);
      this.socket = ws;

      ws.onopen = () => {
        this.onStatusCallback?.(true);
        this.startPinger();
      };

      ws.onmessage = (e) => {
        try {
          const data = JSON.parse(e.data);
          this.onEventCallback?.(data);
        } catch {
          // ignore non-json messages (e.g. pong)
        }
      };

      ws.onerror = () => {
        this.onStatusCallback?.(false);
      };

      ws.onclose = () => {
        this.onStatusCallback?.(false);
        this.stopPinger();
        if (!this.isClosedManually) {
          // Schedule reconnect in 4 seconds
          this.reconnectTimeout = setTimeout(() => {
            this.connect();
          }, 4000);
        }
      };
    } catch {
      this.onStatusCallback?.(false);
      if (!this.isClosedManually) {
        this.reconnectTimeout = setTimeout(() => {
          this.connect();
        }, 5000);
      }
    }
  }

  private startPinger(): void {
    this.stopPinger();
    this.pingInterval = setInterval(() => {
      if (this.socket && this.socket.readyState === WebSocket.OPEN) {
        this.socket.send('ping');
      }
    }, 15000);
  }

  private stopPinger(): void {
    if (this.pingInterval) {
      clearInterval(this.pingInterval);
      this.pingInterval = null;
    }
  }

  private cleanup(): void {
    this.stopPinger();
    if (this.reconnectTimeout) {
      clearTimeout(this.reconnectTimeout);
      this.reconnectTimeout = null;
    }
    if (this.socket) {
      try {
        this.socket.close();
      } catch {}
      this.socket = null;
    }
  }

  public close(): void {
    this.isClosedManually = true;
    this.cleanup();
    this.onStatusCallback?.(false);
  }
}
