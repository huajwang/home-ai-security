import React, { useEffect, useRef, useState } from 'react';
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  TouchableOpacity,
  SafeAreaView,
  Modal,
  ActivityIndicator,
  Alert,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { HubClient } from '../api/hubClient';
import {
  LAN_HTTP_URL,
  SessionStore,
  TAILSCALE_DOMAIN_HTTPS_URL,
  TAILSCALE_HTTP_URL,
} from '../storage/sessionStore';

type IonName = React.ComponentProps<typeof Ionicons>['name'];

interface ConnectionChoice {
  id: string;
  title: string;
  detail: string;
  url: string;
}

interface PairDevice {
  id: string;
  title: string;
  subtitle: string;
  icon: IonName;
  kind: 'zigbee' | 'lock';
  steps: string[];
}

const CONNECTIONS: ConnectionChoice[] = [
  {
    id: 'home',
    title: 'Home Wi-Fi',
    detail: 'This phone and the hub are on the same network.',
    url: LAN_HTTP_URL,
  },
  {
    id: 'away-secure',
    title: 'Away from home',
    detail: 'Encrypted connection when you are not on home Wi-Fi.',
    url: TAILSCALE_DOMAIN_HTTPS_URL,
  },
  {
    id: 'away-direct',
    title: 'Away, alternate',
    detail: 'Use this if the encrypted connection does not open.',
    url: TAILSCALE_HTTP_URL,
  },
];

const DEVICES: PairDevice[] = [
  {
    id: 'bulb',
    title: 'Light',
    subtitle: 'Zigbee bulb',
    icon: 'bulb-outline',
    kind: 'zigbee',
    steps: [
      'Stand near the hub with the bulb powered.',
      'Tap Start pairing.',
      'Turn the bulb off for 5 seconds, then on again.',
      'The home screen can turn it on and off after it joins.',
    ],
  },
  {
    id: 'lock',
    title: 'Door lock',
    subtitle: 'Front door',
    icon: 'lock-closed-outline',
    kind: 'lock',
    steps: [
      'Stand next to the lock.',
      'Tap Start pairing. The lock uses its own radio.',
      'Press the pair button on the lock until it flashes or beeps.',
      'The home screen shows Locked or Unlocked when it has joined.',
    ],
  },
  {
    id: 'remote',
    title: 'Scene remote',
    subtitle: 'Four buttons',
    icon: 'grid-outline',
    kind: 'zigbee',
    steps: [
      'Stand near the hub with the remote.',
      'Tap Start pairing.',
      'Hold button 1 for 10 seconds, until the lights flash quickly.',
      'A steady light is not pairing. Quick flashing means it is joining.',
    ],
  },
  {
    id: 'door',
    title: 'Door sensor',
    subtitle: 'Open and closed',
    icon: 'enter-outline',
    kind: 'zigbee',
    steps: [
      'Put in two AAA alkaline batteries if they are not already in.',
      'Tap Start pairing, then hold the pin in the reset hole for 5 seconds.',
      'The LED should blink quickly. Leave the sensor next to the hub.',
      'When the blinking stops, separate the pieces and bring them together. Home should show Opened, then Closed.',
    ],
  },
];

const ZIGBEE_SECONDS = 180;

interface SettingsScreenProps {
  visible: boolean;
  hubUrl: string;
  onClose: () => void;
  onHubUrl: (url: string) => void;
  onSignOut: () => void;
  onJoined?: () => void;
}

type PairPhase = 'ready' | 'listening' | 'joined' | 'timeout';

export const SettingsScreen: React.FC<SettingsScreenProps> = ({
  visible,
  hubUrl,
  onClose,
  onHubUrl,
  onSignOut,
  onJoined,
}) => {
  const [device, setDevice] = useState<PairDevice | null>(null);
  const [starting, setStarting] = useState(false);
  const [remaining, setRemaining] = useState(0);
  const [phase, setPhase] = useState<PairPhase>('ready');
  const [cloudUrl, setCloudUrl] = useState('');
  const baseline = useRef<Set<string>>(new Set());
  const phaseRef = useRef<PairPhase>('ready');

  useEffect(() => {
    phaseRef.current = phase;
  }, [phase]);

  useEffect(() => {
    if (!visible) return;
    let cancel = false;
    (async () => {
      const saved = await SessionStore.getCloudLinkUrl();
      if (!cancel && saved) setCloudUrl(saved);
      try {
        const status = await HubClient.getSystemStatus();
        if (!cancel && status.linkUrl) {
          await SessionStore.setCloudLinkUrl(status.linkUrl);
          setCloudUrl(status.linkUrl);
        }
      } catch {
        // The phone is away from the hub. The saved cloud address is still usable.
      }
    })();
    return () => {
      cancel = true;
    };
  }, [visible]);

  useEffect(() => {
    if (!visible) {
      setDevice(null);
      setRemaining(0);
      setPhase('ready');
    }
  }, [visible]);

  useEffect(() => {
    if (phase !== 'listening' || remaining <= 0) return;
    const timer = setInterval(() => {
      setRemaining((current) => (current > 0 ? current - 1 : 0));
    }, 1000);
    return () => clearInterval(timer);
  }, [phase === 'listening' && remaining > 0]);

  useEffect(() => {
    if (phase === 'listening' && remaining === 0) setPhase('timeout');
  }, [phase, remaining]);

  useEffect(() => {
    if (!device || (phase !== 'listening' && phase !== 'timeout')) return;
    let cancel = false;
    const look = async () => {
      try {
        const ids = await deviceIds(device);
        if (cancel || phaseRef.current === 'joined') return;
        if (ids.some((id) => id && !baseline.current.has(id))) {
          setPhase('joined');
          setRemaining(0);
          onJoined?.();
        }
      } catch {
        // Keep the current result. The next check will try again.
      }
    };
    look();
    const timer = setInterval(look, 3000);
    return () => {
      cancel = true;
      clearInterval(timer);
    };
  }, [device, phase === 'listening' || phase === 'timeout', onJoined]);

  const chooseConnection = async (url: string) => {
    await SessionStore.setHubUrl(url);
    onHubUrl(url);
  };

  const chooseCloudLink = async () => {
    if (!cloudUrl) {
      Alert.alert(
        'Cloud Link has no address yet',
        'On home Wi-Fi, open Settings once. The hub shares its cloud address. Tailscale keeps working either way.',
      );
      return;
    }
    await chooseConnection(cloudUrl);
  };

  const confirmSignOut = () => {
    Alert.alert('Sign out?', 'You can sign in again on this phone.', [
      { text: 'Cancel', style: 'cancel' },
      { text: 'Sign out', style: 'destructive', onPress: onSignOut },
    ]);
  };

  const startPairing = async () => {
    if (!device) return;
    setStarting(true);
    try {
      const known = await deviceIds(device);
      baseline.current = new Set(known.filter(Boolean));
      if (device.kind === 'zigbee') {
        const seconds = await HubClient.pairZigbee(ZIGBEE_SECONDS);
        setRemaining(seconds);
      } else {
        await HubClient.pairLock();
        setRemaining(120);
      }
      setPhase('listening');
    } catch (err: any) {
      Alert.alert('Pairing did not start', err?.message || 'The hub could not open pairing.');
    } finally {
      setStarting(false);
    }
  };

  return (
    <Modal visible={visible} animationType="slide" presentationStyle="pageSheet" onRequestClose={onClose}>
      <SafeAreaView style={styles.screen}>
        <View style={styles.header}>
          {device ? (
            <TouchableOpacity style={styles.headerButton} onPress={() => setDevice(null)}>
              <Ionicons name="chevron-back" size={22} color="#F8FAFC" />
            </TouchableOpacity>
          ) : (
            <View style={styles.headerButton} />
          )}
          <Text style={styles.headerTitle}>{device ? device.title : 'Settings'}</Text>
          <TouchableOpacity style={styles.headerButton} onPress={onClose}>
            <Ionicons name="close" size={22} color="#94A3B8" />
          </TouchableOpacity>
        </View>

        {device ? (
          <PairingGuide
            device={device}
            starting={starting}
            remaining={remaining}
            phase={phase}
            onStart={startPairing}
            onDone={() => setDevice(null)}
          />
        ) : (
          <ScrollView contentContainerStyle={styles.body}>
            <Text style={styles.sectionLabel}>Connection</Text>
            <View style={styles.group}>
              {CONNECTIONS.map((choice, index) => {
                const selected = hubUrl === choice.url;
                return (
                  <TouchableOpacity
                    key={choice.id}
                    style={[styles.row, index > 0 && styles.rowBorder]}
                    onPress={() => chooseConnection(choice.url)}
                  >
                    <View style={styles.rowText}>
                      <Text style={styles.rowTitle}>{choice.title}</Text>
                      <Text style={styles.rowDetail}>{choice.detail}</Text>
                      <Text style={styles.rowAddress}>{hostOf(choice.url)}</Text>
                    </View>
                    <Ionicons
                      name={selected ? 'checkmark-circle' : 'ellipse-outline'}
                      size={22}
                      color={selected ? '#38BDF8' : '#334155'}
                    />
                  </TouchableOpacity>
                );
              })}
              <TouchableOpacity
                style={[styles.row, styles.rowBorder]}
                onPress={chooseCloudLink}
              >
                <View style={styles.rowText}>
                  <Text style={styles.rowTitle}>Cloud Link</Text>
                  <Text style={styles.rowDetail}>
                    Reach this hub from outside without installing Tailscale. The hub calls out. Your router stays closed.
                  </Text>
                  <Text style={styles.rowAddress}>{cloudUrl ? hostOf(cloudUrl) : 'Waiting for an address from the hub'}</Text>
                </View>
                <Ionicons
                  name={hubUrl === cloudUrl && cloudUrl ? 'checkmark-circle' : 'ellipse-outline'}
                  size={22}
                  color={hubUrl === cloudUrl && cloudUrl ? '#38BDF8' : '#334155'}
                />
              </TouchableOpacity>
            </View>

            <Text style={styles.sectionLabel}>Add a device</Text>
            <View style={styles.group}>
              {DEVICES.map((item, index) => (
                <TouchableOpacity
                  key={item.id}
                  style={[styles.row, index > 0 && styles.rowBorder]}
                  onPress={() => {
                    setRemaining(0);
                    setPhase('ready');
                    setDevice(item);
                  }}
                >
                  <View style={styles.deviceIcon}>
                    <Ionicons name={item.icon} size={20} color="#38BDF8" />
                  </View>
                  <View style={styles.rowText}>
                    <Text style={styles.rowTitle}>{item.title}</Text>
                    <Text style={styles.rowDetail}>{item.subtitle}</Text>
                  </View>
                  <Ionicons name="chevron-forward" size={18} color="#475569" />
                </TouchableOpacity>
              ))}
            </View>

            <Text style={styles.sectionLabel}>Account</Text>
            <View style={styles.group}>
              <TouchableOpacity style={styles.row} onPress={confirmSignOut}>
                <Text style={styles.signOut}>Sign out</Text>
              </TouchableOpacity>
            </View>
          </ScrollView>
        )}
      </SafeAreaView>
    </Modal>
  );
};

const PairingGuide: React.FC<{
  device: PairDevice;
  starting: boolean;
  remaining: number;
  phase: PairPhase;
  onStart: () => void;
  onDone: () => void;
}> = ({ device, starting, remaining, phase, onStart, onDone }) => {
  const outcome = outcomeCopy(device, phase, remaining);
  return (
    <ScrollView contentContainerStyle={styles.body}>
      <View style={styles.hero}>
        <View style={[styles.heroIcon, phase === 'joined' && styles.heroIconJoined, phase === 'timeout' && styles.heroIconTimeout]}>
          <Ionicons name={outcome.icon} size={28} color={outcome.color} />
        </View>
        <Text style={styles.heroTitle}>{outcome.title}</Text>
        <Text style={styles.heroDetail}>{outcome.detail}</Text>
      </View>

      {phase !== 'joined' && (
        <View style={styles.group}>
          {device.steps.map((step, index) => (
            <View key={step} style={[styles.step, index > 0 && styles.rowBorder]}>
              <View style={styles.stepNumber}>
                <Text style={styles.stepNumberText}>{index + 1}</Text>
              </View>
              <Text style={styles.stepText}>{step}</Text>
            </View>
          ))}
        </View>
      )}

      <TouchableOpacity
        style={[styles.primary, phase === 'listening' && styles.primaryQuiet, phase === 'joined' && styles.primaryJoined]}
        onPress={phase === 'joined' ? onDone : onStart}
        disabled={starting}
      >
        {starting ? (
          <ActivityIndicator color="#FFF" />
        ) : (
          <Text style={styles.primaryText}>{outcome.action}</Text>
        )}
      </TouchableOpacity>
    </ScrollView>
  );
};

async function deviceIds(device: PairDevice): Promise<string[]> {
  if (device.id === 'door') return HubClient.listContactIds();
  if (device.id === 'bulb') return HubClient.listLightIds();
  if (device.id === 'remote') return HubClient.listRemoteIds();
  const lock = await HubClient.getLockStatus();
  return [`${lock.state}|${lock.updatedAt || ''}|${lock.reachable || ''}`];
}

function outcomeCopy(
  device: PairDevice,
  phase: PairPhase,
  remaining: number
): { icon: IonName; color: string; title: string; detail: string; action: string } {
  if (phase === 'joined') {
    return {
      icon: 'checkmark-circle',
      color: '#10B981',
      title: `${device.title} joined`,
      detail: joinedDetail(device),
      action: 'Done',
    };
  }
  if (phase === 'timeout') {
    return {
      icon: 'alert-circle',
      color: '#F59E0B',
      title: 'No device joined',
      detail: 'The hub stopped listening. Move the device closer and follow the steps again.',
      action: 'Try again',
    };
  }
  if (phase === 'listening') {
    return {
      icon: device.icon,
      color: '#38BDF8',
      title: 'Listening for the device',
      detail: `${formatRemaining(remaining)} left. Stay near the hub and follow the steps below.`,
      action: 'Listen again',
    };
  }
  return {
    icon: device.icon,
    color: '#38BDF8',
    title: 'Ready to add',
    detail: 'The hub accepts one new device at a time. Stay within a few feet of it.',
    action: 'Start pairing',
  };
}

function joinedDetail(device: PairDevice): string {
  if (device.id === 'door') {
    return 'It is on the home screen. Separate the two pieces, then bring them together. The status should change between Opened and Closed.';
  }
  if (device.id === 'bulb') return 'You can turn it on and off from the home screen.';
  if (device.id === 'remote') {
    return 'Button 1 arms the system. Button 2 toggles the light. Hold button 4 for about 5 seconds to raise an alert.';
  }
  return 'The home screen shows Locked or Unlocked.';
}

function hostOf(url: string): string {
  try {
    return new URL(url).host;
  } catch {
    return url;
  }
}

function formatRemaining(seconds: number): string {
  const minutes = Math.floor(seconds / 60);
  const rest = seconds % 60;
  return `${minutes}:${rest.toString().padStart(2, '0')}`;
}

const styles = StyleSheet.create({
  screen: {
    flex: 1,
    backgroundColor: '#0B0F19',
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: 12,
    paddingVertical: 8,
  },
  headerButton: {
    width: 40,
    height: 40,
    alignItems: 'center',
    justifyContent: 'center',
  },
  headerTitle: {
    color: '#F8FAFC',
    fontSize: 17,
    fontWeight: '700',
  },
  body: {
    padding: 20,
    paddingBottom: 40,
    gap: 10,
  },
  sectionLabel: {
    color: '#64748B',
    fontSize: 13,
    fontWeight: '600',
    marginTop: 12,
    marginLeft: 4,
  },
  group: {
    backgroundColor: '#161E2E',
    borderRadius: 16,
    borderWidth: 1,
    borderColor: '#1E293B',
    overflow: 'hidden',
  },
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    paddingHorizontal: 16,
    paddingVertical: 14,
  },
  rowBorder: {
    borderTopWidth: 1,
    borderTopColor: '#1E293B',
  },
  rowText: {
    flex: 1,
    gap: 2,
  },
  rowTitle: {
    color: '#F8FAFC',
    fontSize: 16,
    fontWeight: '600',
  },
  rowDetail: {
    color: '#94A3B8',
    fontSize: 13,
    lineHeight: 18,
  },
  rowAddress: {
    color: '#64748B',
    fontSize: 12,
    marginTop: 2,
  },
  deviceIcon: {
    width: 36,
    height: 36,
    borderRadius: 18,
    backgroundColor: '#0F172A',
    alignItems: 'center',
    justifyContent: 'center',
  },
  signOut: {
    color: '#F87171',
    fontSize: 16,
    fontWeight: '600',
  },
  hero: {
    alignItems: 'flex-start',
    gap: 8,
    marginBottom: 8,
  },
  heroIcon: {
    width: 52,
    height: 52,
    borderRadius: 26,
    backgroundColor: 'rgba(56, 189, 248, 0.12)',
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: 4,
  },
  heroIconJoined: {
    backgroundColor: 'rgba(16, 185, 129, 0.15)',
  },
  heroIconTimeout: {
    backgroundColor: 'rgba(245, 158, 11, 0.15)',
  },
  heroTitle: {
    color: '#F8FAFC',
    fontSize: 22,
    fontWeight: '700',
  },
  heroDetail: {
    color: '#94A3B8',
    fontSize: 15,
    lineHeight: 22,
  },
  step: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: 12,
    paddingHorizontal: 16,
    paddingVertical: 14,
  },
  stepNumber: {
    width: 24,
    height: 24,
    borderRadius: 12,
    backgroundColor: '#0F172A',
    alignItems: 'center',
    justifyContent: 'center',
  },
  stepNumberText: {
    color: '#38BDF8',
    fontSize: 13,
    fontWeight: '700',
  },
  stepText: {
    flex: 1,
    color: '#E2E8F0',
    fontSize: 15,
    lineHeight: 21,
  },
  primary: {
    marginTop: 16,
    backgroundColor: '#2563EB',
    borderRadius: 14,
    minHeight: 52,
    alignItems: 'center',
    justifyContent: 'center',
  },
  primaryQuiet: {
    backgroundColor: '#1E293B',
    borderWidth: 1,
    borderColor: '#334155',
  },
  primaryJoined: {
    backgroundColor: '#059669',
  },
  primaryText: {
    color: '#FFF',
    fontSize: 16,
    fontWeight: '700',
  },
});
