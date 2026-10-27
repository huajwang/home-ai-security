import { SessionStore } from '../storage/sessionStore';
import {
  AssistantMedia,
  AssistantResponse,
  DoorContact,
  DoorEvent,
  EventSearch,
  LockStatus,
  Session,
  SystemStatus,
} from '../types/models';

export class HubError extends Error {
  constructor(public code: string, message: string) {
    super(message);
    this.name = 'HubError';
  }
}

function idsFrom(raw: any): string[] {
  if (!Array.isArray(raw)) return [];
  return raw.map((item) => String(item?.ieee || '')).filter(Boolean);
}

export class HubClient {
  private static async request<T = any>(
    path: string,
    options: {
      method?: 'GET' | 'POST' | 'DELETE';
      body?: any;
      auth?: boolean;
    } = {}
  ): Promise<T> {
    const { method = 'GET', body, auth = true } = options;
    const baseUrl = await SessionStore.getHubUrl();
    const url = `${baseUrl}${path}`;

    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
      Accept: 'application/json',
    };

    if (auth) {
      const token = await SessionStore.getAccessToken();
      if (!token) {
        throw new HubError('unauthorized', 'No access token found');
      }
      headers['Authorization'] = `Bearer ${token}`;
    }

    let response: Response;
    try {
      response = await fetch(url, {
        method,
        headers,
        body: body ? JSON.stringify(body) : undefined,
      });
    } catch (err: any) {
      const msg = err?.message || 'Network request failed';
      throw new HubError('network_error', `Cannot reach Hub at ${baseUrl}: ${msg}`);
    }

    if (response.status === 401 && auth) {
      // Try token refresh
      const refreshed = await HubClient.tryRefresh();
      if (refreshed) {
        // Retry once with new token
        const newToken = await SessionStore.getAccessToken();
        headers['Authorization'] = `Bearer ${newToken}`;
        response = await fetch(url, {
          method,
          headers,
          body: body ? JSON.stringify(body) : undefined,
        });
      }
    }

    let json: any = {};
    const text = await response.text();
    if (text) {
      try {
        json = JSON.parse(text);
      } catch {
        json = { raw: text };
      }
    }

    if (!response.ok) {
      const detail = json?.detail || json?.message || response.statusText;
      const code = json?.code || `http_${response.status}`;
      throw new HubError(code, detail);
    }

    return json as T;
  }

  static async tryRefresh(): Promise<boolean> {
    const refreshToken = await SessionStore.getRefreshToken();
    if (!refreshToken) return false;

    try {
      const baseUrl = await SessionStore.getHubUrl();
      const res = await fetch(`${baseUrl}/v1/auth/refresh`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh_token: refreshToken }),
      });
      if (!res.ok) return false;
      const data = await res.json();
      await SessionStore.saveSession(HubClient.parseSession(data));
      return true;
    } catch {
      return false;
    }
  }

  private static parseSession(obj: any): Session {
    return {
      accessToken: obj.access_token,
      refreshToken: obj.refresh_token,
      user: {
        id: obj.user?.id || 1,
        username: obj.user?.username || 'owner',
        role: obj.user?.role || 'owner',
        canUnlock: !!obj.user?.can_unlock,
      },
      home: {
        name: obj.home?.name || 'Home',
      },
      device: obj.device
        ? {
            id: obj.device.id,
            deviceName: obj.device.device_name,
            deviceRole: obj.device.device_role,
          }
        : undefined,
    };
  }

  static async login(
    username: string,
    password: string,
    deviceName = 'iPhone',
    deviceRole = 'phone'
  ): Promise<Session> {
    const body = {
      username,
      password,
      device_name: deviceName,
      device_role: deviceRole,
    };
    const obj = await HubClient.request<any>('/v1/auth/login', {
      method: 'POST',
      body,
      auth: false,
    });
    const session = HubClient.parseSession(obj);
    await SessionStore.saveSession(session);
    return session;
  }

  static async getSystemStatus(): Promise<SystemStatus> {
    const obj = await HubClient.request<any>('/v1/system');
    const vision = obj.vision || {};
    const lock = obj.lock || {};
    return {
      armed: !!obj.armed,
      alarmActive: !!obj.alarm_active,
      visionFps: vision.fps ?? 0.0,
      visionRunning: !!vision.running,
      lastPersonAt: vision.last_person_at && vision.last_person_at !== 'null' ? vision.last_person_at : null,
      lockState: lock.state || 'unknown',
      lockAdapter: lock.adapter || 'mock',
      hubTime: obj.hub_time || new Date().toISOString(),
      contacts: HubClient.parseContacts(obj.contacts),
    };
  }

  static async arm(): Promise<SystemStatus> {
    await HubClient.request('/v1/system/arm', { method: 'POST' });
    return HubClient.getSystemStatus();
  }

  static async disarm(): Promise<SystemStatus> {
    await HubClient.request('/v1/system/disarm', { method: 'POST' });
    return HubClient.getSystemStatus();
  }

  static async getEvents(limit = 50): Promise<DoorEvent[]> {
    const obj = await HubClient.request<any>(`/v1/events?limit=${limit}`);
    return HubClient.parseEvents(obj);
  }

  static async searchEvents(question: string): Promise<EventSearch> {
    const encoded = encodeURIComponent(question.trim());
    const obj = await HubClient.request<any>(`/v1/events/search?q=${encoded}`);
    const filter = obj.filter;
    return {
      understood: !!filter?.understood,
      events: HubClient.parseEvents(obj),
    };
  }

  static async assistantChat(prompt: string): Promise<AssistantResponse> {
    const obj = await HubClient.request<any>('/v1/assistant/chat', {
      method: 'POST',
      body: { prompt },
    });
    const rawMedia = obj.tool_data?.media;
    const media: AssistantMedia[] = Array.isArray(rawMedia)
      ? rawMedia
          .filter((item: any) => item?.snapshot_url)
          .slice(0, 3)
          .map((item: any) => ({
            id: item.id,
            ts: item.ts,
            label: item.label,
            camera: item.camera ?? null,
            snapshotUrl: item.snapshot_url,
            clipUrl: item.clip_url || null,
          }))
      : [];
    return {
      response: obj.response || 'No response received from Assistant.',
      toolUsed: obj.tool_used || 'general_llm',
      media,
    };
  }

  static async getLockStatus(): Promise<LockStatus> {
    const obj = await HubClient.request<any>('/v1/lock');
    return {
      state: obj.state || 'unknown',
      updatedAt: obj.updated_at,
      adapter: obj.adapter,
      reachable: obj.reachable || 'unknown',
    };
  }

  static async lockDoor(): Promise<LockStatus> {
    const obj = await HubClient.request<any>('/v1/lock/lock', { method: 'POST' });
    return {
      state: obj.state,
      updatedAt: obj.updated_at,
      adapter: obj.adapter,
      reachable: obj.reachable || 'unknown',
    };
  }

  static async unlockDoor(): Promise<LockStatus> {
    const obj = await HubClient.request<any>('/v1/lock/unlock', {
      method: 'POST',
      body: { confirm: true },
    });
    return {
      state: obj.state,
      updatedAt: obj.updated_at,
      adapter: obj.adapter,
      reachable: obj.reachable || 'unknown',
    };
  }

  static async lightOn(): Promise<string> {
    const obj = await HubClient.request<any>('/v1/lights/on', { method: 'POST' });
    return `Light ${obj.state || 'on'}`;
  }

  static async lightOff(): Promise<string> {
    const obj = await HubClient.request<any>('/v1/lights/off', { method: 'POST' });
    return `Light ${obj.state || 'off'}`;
  }

  static async pairZigbee(seconds = 180): Promise<number> {
    const obj = await HubClient.request<any>('/v1/lights/pair', {
      method: 'POST',
      body: { seconds },
    });
    return Number(obj.seconds) || seconds;
  }

  static async pairBulb(): Promise<string> {
    const seconds = await HubClient.pairZigbee();
    return `Listening for a bulb for ${seconds} seconds`;
  }

  static async listContactIds(): Promise<string[]> {
    const obj = await HubClient.request<any>('/v1/contacts');
    return idsFrom(obj.contacts);
  }

  static async listLightIds(): Promise<string[]> {
    const obj = await HubClient.request<any>('/v1/lights');
    return idsFrom(obj.lights);
  }

  static async listRemoteIds(): Promise<string[]> {
    const obj = await HubClient.request<any>('/v1/lights');
    return idsFrom(obj.remotes);
  }

  static async pairLock(): Promise<string> {
    const obj = await HubClient.request<any>('/v1/lock/pair', { method: 'POST' });
    return obj.message || 'Lock pairing started';
  }

  static async getWsUrl(): Promise<string> {
    const baseUrl = await SessionStore.getHubUrl();
    const token = (await SessionStore.getAccessToken()) || '';
    const wsBase = baseUrl.replace(/^https:\/\//i, 'wss://').replace(/^http:\/\//i, 'ws://');
    return `${wsBase}/v1/stream/events?access_token=${token}`;
  }

  static async getCameraLiveUrl(camera: 'door' | 'driveway'): Promise<string> {
    const baseUrl = await SessionStore.getHubUrl();
    const token = (await SessionStore.getAccessToken()) || '';
    const wsBase = baseUrl.replace(/^https:\/\//i, 'wss://').replace(/^http:\/\//i, 'ws://');
    const path = camera === 'door' ? '/v1/system/live' : '/v1/driveway/live';
    return `${wsBase}${path}?access_token=${encodeURIComponent(token)}`;
  }

  static async getDoorSnapshotUrl(): Promise<string> {
    const baseUrl = await SessionStore.getHubUrl();
    const token = (await SessionStore.getAccessToken()) || '';
    return `${baseUrl}/v1/system/snapshot?access_token=${token}&t=${Date.now()}`;
  }

  static async getDrivewaySnapshotUrl(): Promise<string> {
    const baseUrl = await SessionStore.getHubUrl();
    const token = (await SessionStore.getAccessToken()) || '';
    return `${baseUrl}/v1/driveway/snapshot?access_token=${token}&t=${Date.now()}`;
  }

  static async getEventSnapshotUrl(relative: string): Promise<string> {
    const baseUrl = await SessionStore.getHubUrl();
    const token = (await SessionStore.getAccessToken()) || '';
    const delimiter = relative.includes('?') ? '&' : '?';
    return `${baseUrl}${relative}${delimiter}access_token=${token}`;
  }

  private static parseContacts(raw: any): DoorContact[] {
    if (!Array.isArray(raw)) return [];
    return raw
      .filter((item: any) => item && item.ieee)
      .map((item: any) => ({
        ieee: String(item.ieee),
        name: item.name || 'Door',
        open: item.open === true ? true : item.open === false ? false : null,
        updatedAt: item.updated_at || null,
        model: item.model || null,
      }));
  }

  private static parseEvents(obj: any): DoorEvent[] {
    const list = obj.events || [];
    return list.map((item: any) => ({
      id: item.id,
      ts: item.ts,
      label: item.label,
      confidence: item.confidence ?? 0.0,
      maskDetected: Boolean(item.mask_detected),
      maskStatus: item.mask_status || (item.mask_detected ? 'masked' : 'unmasked'),
      snapshotUrl: item.snapshot_url && item.snapshot_url !== 'null' ? item.snapshot_url : null,
      camera: item.camera && item.camera !== 'null' ? item.camera : null,
    }));
  }
}
