export interface User {
  id: number;
  username: string;
  role: string;
  canUnlock: boolean;
}

export interface Device {
  id: number;
  deviceName: string;
  deviceRole: string;
}

export interface Home {
  name: string;
}

export interface Session {
  accessToken: string;
  refreshToken: string;
  user: User;
  home: Home;
  device?: Device;
}

export interface SystemStatus {
  armed: boolean;
  alarmActive: boolean;
  visionFps: number;
  visionRunning: boolean;
  lastPersonAt?: string | null;
  lockState: string;
  lockAdapter: string;
  hubTime: string;
}

export interface DoorEvent {
  id: number;
  ts: string;
  label: string;
  confidence: number;
  snapshotUrl?: string | null;
  camera?: string | null;
}

export interface EventSearch {
  understood: boolean;
  events: DoorEvent[];
}

export interface LockStatus {
  state: string;
  updatedAt?: string;
  adapter?: string;
}

export interface AssistantResponse {
  response: string;
  toolUsed: string;
}
