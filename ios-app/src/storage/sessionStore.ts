import AsyncStorage from '@react-native-async-storage/async-storage';
import { Session, User } from '../types/models';

const STORAGE_KEYS = {
  HUB_URL: '@home_ai:hub_url',
  ACCESS_TOKEN: '@home_ai:access_token',
  REFRESH_TOKEN: '@home_ai:refresh_token',
  USER_DATA: '@home_ai:user_data',
  HOME_NAME: '@home_ai:home_name',
  STATION_PIN: '@home_ai:station_pin',
  CLOUD_LINK_URL: '@home_ai:cloud_link_url',
};

export const TAILSCALE_DOMAIN_HTTPS_URL = 'https://rock-5t.tailff6218.ts.net:8443';
export const TAILSCALE_HTTP_URL = 'http://100.87.220.55:8080';
export const TAILSCALE_HTTPS_URL = 'https://100.87.220.55:8443';
export const LAN_HTTP_URL = 'http://10.0.0.83:8080';
export const LAN_HTTPS_URL = 'https://10.0.0.83:8443';

export const DEFAULT_HUB_URL = TAILSCALE_DOMAIN_HTTPS_URL;
export const LAN_HUB_URL = LAN_HTTP_URL;

export class SessionStore {
  static async getHubUrl(): Promise<string> {
    const url = await AsyncStorage.getItem(STORAGE_KEYS.HUB_URL);
    return url || DEFAULT_HUB_URL;
  }

  static async setHubUrl(url: string): Promise<void> {
    const trimmed = url.trim().replace(/\/+$/, '');
    await AsyncStorage.setItem(STORAGE_KEYS.HUB_URL, trimmed);
  }

  static async getAccessToken(): Promise<string | null> {
    return AsyncStorage.getItem(STORAGE_KEYS.ACCESS_TOKEN);
  }

  static async getRefreshToken(): Promise<string | null> {
    return AsyncStorage.getItem(STORAGE_KEYS.REFRESH_TOKEN);
  }

  static async getUser(): Promise<User | null> {
    const json = await AsyncStorage.getItem(STORAGE_KEYS.USER_DATA);
    if (!json) return null;
    try {
      return JSON.parse(json);
    } catch {
      return null;
    }
  }

  static async getStationPin(): Promise<string> {
    const pin = await AsyncStorage.getItem(STORAGE_KEYS.STATION_PIN);
    return pin || '1234';
  }

  static async getCloudLinkUrl(): Promise<string> {
    return (await AsyncStorage.getItem(STORAGE_KEYS.CLOUD_LINK_URL)) || '';
  }

  static async setCloudLinkUrl(url: string): Promise<void> {
    const trimmed = url.trim().replace(/\/+$/, '');
    if (!trimmed) {
      await AsyncStorage.removeItem(STORAGE_KEYS.CLOUD_LINK_URL);
      return;
    }
    await AsyncStorage.setItem(STORAGE_KEYS.CLOUD_LINK_URL, trimmed);
  }

  static async saveSession(session: Session): Promise<void> {
    await AsyncStorage.multiSet([
      [STORAGE_KEYS.ACCESS_TOKEN, session.accessToken],
      [STORAGE_KEYS.REFRESH_TOKEN, session.refreshToken],
      [STORAGE_KEYS.USER_DATA, JSON.stringify(session.user)],
      [STORAGE_KEYS.HOME_NAME, session.home.name || 'Home'],
    ]);
  }

  static async clearSession(): Promise<void> {
    await AsyncStorage.multiRemove([
      STORAGE_KEYS.ACCESS_TOKEN,
      STORAGE_KEYS.REFRESH_TOKEN,
      STORAGE_KEYS.USER_DATA,
      STORAGE_KEYS.HOME_NAME,
    ]);
  }
}
