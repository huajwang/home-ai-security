import React, { useState, useEffect, useCallback, useRef } from 'react';
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  TouchableOpacity,
  RefreshControl,
  TextInput,
  Alert,
  ActivityIndicator,
  SafeAreaView,
  Platform,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { HubClient } from '../api/hubClient';
import { EventSocket } from '../api/eventSocket';
import {
  SessionStore,
  TAILSCALE_DOMAIN_HTTPS_URL,
  TAILSCALE_HTTP_URL,
  LAN_HTTP_URL,
} from '../storage/sessionStore';
import { DoorEvent, LockStatus, MeetingMinutes, SystemStatus, TaskItem } from '../types/models';
import { UnlockHelper } from '../utils/unlockHelper';
import { SnapshotModal } from '../components/SnapshotModal';
import { AssistantModal } from '../components/AssistantModal';
import { CameraLive } from '../components/CameraLive';

interface HomeScreenProps {
  onLogout: () => void;
}

export const HomeScreen: React.FC<HomeScreenProps> = ({ onLogout }) => {
  const [hubUrl, setHubUrl] = useState('');
  const [system, setSystem] = useState<SystemStatus | null>(null);
  const [lock, setLock] = useState<LockStatus | null>(null);
  const [events, setEvents] = useState<DoorEvent[]>([]);
  const [meetingActive, setMeetingActive] = useState(false);
  const [minutes, setMinutes] = useState<MeetingMinutes | null>(null);
  const [tasks, setTasks] = useState<TaskItem[]>([]);
  const [refreshing, setRefreshing] = useState(false);
  const [loadingAction, setLoadingAction] = useState<string | null>(null);
  const [wsConnected, setWsConnected] = useState(false);

  // Search state
  const [searchQuery, setSearchQuery] = useState('');
  const [isSearching, setIsSearching] = useState(false);
  const [searchUnderstood, setSearchUnderstood] = useState<boolean | null>(null);

  // Modals
  const [selectedEvent, setSelectedEvent] = useState<DoorEvent | null>(null);
  const [assistantVisible, setAssistantVisible] = useState(false);

  // Cameras state
  const [selectedCam, setSelectedCam] = useState<'door' | 'driveway'>('door');

  const socketRef = useRef<EventSocket | null>(null);

  const loadAllData = useCallback(async () => {
    try {
      const [sysStatus, lockStatus, eventList, active, latest, openTasks] = await Promise.all([
        HubClient.getSystemStatus(),
        HubClient.getLockStatus(),
        HubClient.getEvents(30),
        HubClient.getActiveMeeting(),
        HubClient.getLatestMeeting(),
        HubClient.getTasks(),
      ]);
      setSystem(sysStatus);
      setLock(lockStatus);
      setEvents(eventList);
      setMeetingActive(active?.state === 'recording' || active?.state === 'stopping');
      setMinutes(latest);
      setTasks(openTasks);
      setSearchUnderstood(null);
    } catch (err: any) {
      console.warn('Load data error:', err);
    }
  }, []);

  const onRefresh = async () => {
    setRefreshing(true);
    await loadAllData();
    setRefreshing(false);
  };

  useEffect(() => {
    SessionStore.getHubUrl().then((url) => setHubUrl(url));
    loadAllData();

    // Start WebSocket
    const socket = new EventSocket(
      (event) => {
        if (event?.type === 'lock_changed' && event.state) {
          setLock((current) => ({
            state: event.state,
            updatedAt: event.updated_at || current?.updatedAt,
            adapter: current?.adapter,
            reachable: event.reachable || current?.reachable,
          }));
          return;
        }
        loadAllData();
      },
      (connected) => {
        setWsConnected(connected);
      }
    );
    socket.connect();
    socketRef.current = socket;

    return () => {
      socket.close();
    };
  }, [loadAllData]);

  const handleArmToggle = async () => {
    if (!system) return;
    const isArming = !system.armed;
    setLoadingAction(isArming ? 'arm' : 'disarm');
    try {
      if (isArming) {
        await HubClient.arm();
      } else {
        await HubClient.disarm();
      }
      await loadAllData();
    } catch (err: any) {
      Alert.alert('Arm/Disarm Failed', err?.message || 'Error communicating with Hub');
    } finally {
      setLoadingAction(null);
    }
  };

  const handleLock = async () => {
    setLoadingAction('lock');
    try {
      await HubClient.lockDoor();
      await loadAllData();
    } catch (err: any) {
      Alert.alert('Lock Failed', err?.message || 'Lock operation failed');
    } finally {
      setLoadingAction(null);
    }
  };

  const handleUnlock = async () => {
    // Face ID / Touch ID / PIN confirmation guard!
    await UnlockHelper.confirmUnlock(async () => {
      setLoadingAction('unlock');
      try {
        await HubClient.unlockDoor();
        await loadAllData();
        Alert.alert('Door Unlocked', 'The front door has been unlocked.');
      } catch (err: any) {
        Alert.alert('Unlock Failed', err?.message || 'Unlock operation failed');
      } finally {
        setLoadingAction(null);
      }
    });
  };

  const handleLight = async (turnOn: boolean) => {
    setLoadingAction(turnOn ? 'light_on' : 'light_off');
    try {
      if (turnOn) {
        await HubClient.lightOn();
      } else {
        await HubClient.lightOff();
      }
      await loadAllData();
    } catch (err: any) {
      Alert.alert('Light Control Failed', err?.message || 'Light operation failed');
    } finally {
      setLoadingAction(null);
    }
  };

  const handleDoneTask = async (id: string) => {
    setLoadingAction('task_done');
    try {
      await HubClient.completeTask(id);
      await loadAllData();
    } catch (err: any) {
      Alert.alert('Tasks', err?.message || 'Could not update the list');
    } finally {
      setLoadingAction(null);
    }
  };

  const handlePrintTasks = async () => {
    setLoadingAction('task_print');
    try {
      const message = await HubClient.printTasks();
      Alert.alert('Tasks', message);
    } catch (err: any) {
      Alert.alert('Tasks', err?.message || 'Could not print the list');
    } finally {
      setLoadingAction(null);
    }
  };

  const handleStartMeeting = async () => {
    setLoadingAction('meeting_start');
    try {
      await HubClient.startMeeting();
      setMeetingActive(true);
    } catch (err: any) {
      Alert.alert('Meeting', err?.message || 'Could not start the meeting');
    } finally {
      setLoadingAction(null);
    }
  };

  const handleStopMeeting = async () => {
    setLoadingAction('meeting_stop');
    try {
      await HubClient.stopMeeting();
      for (let attempt = 0; attempt < 15; attempt += 1) {
        await new Promise((resolve) => setTimeout(resolve, 2000));
        const active = await HubClient.getActiveMeeting();
        if (!active || active.state === 'ended') {
          break;
        }
      }
      await loadAllData();
    } catch (err: any) {
      Alert.alert('Meeting', err?.message || 'Could not stop the meeting');
    } finally {
      setLoadingAction(null);
    }
  };

  const handlePairBulb = async () => {
    try {
      const msg = await HubClient.pairBulb();
      Alert.alert('Bulb Pairing', msg);
    } catch (err: any) {
      Alert.alert('Pairing Error', err?.message || 'Failed to start bulb pairing');
    }
  };

  const handlePairLock = async () => {
    try {
      const msg = await HubClient.pairLock();
      Alert.alert('Lock Pairing', msg);
    } catch (err: any) {
      Alert.alert('Pairing Error', err?.message || 'Failed to start lock pairing');
    }
  };

  const handleSearch = async () => {
    if (!searchQuery.trim()) {
      setIsSearching(false);
      loadAllData();
      return;
    }
    setIsSearching(true);
    try {
      const result = await HubClient.searchEvents(searchQuery);
      setEvents(result.events);
      setSearchUnderstood(result.understood);
    } catch (err: any) {
      Alert.alert('Search Failed', err?.message || 'Could not perform AI event search');
    } finally {
      setIsSearching(false);
    }
  };

  const isTailscale = hubUrl.includes('100.87.') || hubUrl.includes('.ts.net');

  return (
    <SafeAreaView style={styles.container}>
      {/* Top App Header */}
      <View style={styles.topBar}>
        <View style={styles.brandContainer}>
          <Text style={styles.brandTitle}>Home AI Security</Text>
          <View style={styles.networkBadge}>
            <View style={[styles.networkDot, wsConnected ? styles.dotGreen : styles.dotOrange]} />
            <Text style={styles.networkText}>
              {wsConnected
                ? isTailscale
                  ? 'Tailscale Live'
                  : 'Home LAN Live'
                : 'Connecting...'}
            </Text>
          </View>
        </View>

        <View style={styles.headerActions}>
          <TouchableOpacity
            style={styles.aiButton}
            onPress={() => setAssistantVisible(true)}
            activeOpacity={0.8}
          >
            <Ionicons name="sparkles" size={18} color="#38BDF8" />
            <Text style={styles.aiButtonText}>AI</Text>
          </TouchableOpacity>

          <TouchableOpacity
            style={styles.iconButton}
            onPress={() => {
              Alert.alert('Session & Network', `Hub URL: ${hubUrl}`, [
                {
                  text: 'Tailscale HTTPS (rock-5t)',
                  onPress: async () => {
                    await SessionStore.setHubUrl(TAILSCALE_DOMAIN_HTTPS_URL);
                    setHubUrl(TAILSCALE_DOMAIN_HTTPS_URL);
                    loadAllData();
                  },
                },
                {
                  text: 'Tailscale HTTP (8080)',
                  onPress: async () => {
                    await SessionStore.setHubUrl(TAILSCALE_HTTP_URL);
                    setHubUrl(TAILSCALE_HTTP_URL);
                    loadAllData();
                  },
                },
                {
                  text: 'LAN HTTP (8080)',
                  onPress: async () => {
                    await SessionStore.setHubUrl(LAN_HTTP_URL);
                    setHubUrl(LAN_HTTP_URL);
                    loadAllData();
                  },
                },
                { text: 'Sign Out', style: 'destructive', onPress: onLogout },
                { text: 'Cancel', style: 'cancel' },
              ]);
            }}
          >
            <Ionicons name="settings-outline" size={20} color="#94A3B8" />
          </TouchableOpacity>
        </View>
      </View>

      <ScrollView
        contentContainerStyle={styles.scrollArea}
        refreshControl={
          <RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor="#3B82F6" />
        }
      >
        {/* System Armed / Alarm Status Banner */}
        <View style={styles.card}>
          <View style={styles.cardHeader}>
            <View style={styles.cardTitleRow}>
              <Ionicons
                name={system?.armed ? 'shield-checkmark' : 'shield-outline'}
                size={22}
                color={system?.armed ? '#EF4444' : '#10B981'}
              />
              <Text style={styles.cardTitle}>System Perimeter</Text>
            </View>

            <View
              style={[
                styles.statusBadge,
                system?.armed ? styles.badgeArmed : styles.badgeDisarmed,
              ]}
            >
              <Text
                style={[
                  styles.statusBadgeText,
                  system?.armed ? styles.textArmed : styles.textDisarmed,
                ]}
              >
                {system?.armed ? 'ARMED' : 'DISARMED'}
              </Text>
            </View>
          </View>

          {system?.alarmActive && (
            <View style={styles.alarmAlertBox}>
              <Ionicons name="warning" size={20} color="#EF4444" />
              <Text style={styles.alarmAlertText}>ALARM TRIGGERED — Strobe / Sirens Active</Text>
            </View>
          )}

          <View style={styles.armButtonGroup}>
            <TouchableOpacity
              style={[
                styles.actionBtn,
                system?.armed ? styles.btnArmedActive : styles.btnInactive,
              ]}
              onPress={handleArmToggle}
              disabled={loadingAction !== null}
            >
              {loadingAction === 'arm' || loadingAction === 'disarm' ? (
                <ActivityIndicator color="#FFF" size="small" />
              ) : (
                <>
                  <Ionicons
                    name={system?.armed ? 'lock-open-outline' : 'shield-checkmark-outline'}
                    size={18}
                    color="#FFF"
                  />
                  <Text style={styles.actionBtnText}>
                    {system?.armed ? 'Disarm System' : 'Arm Perimeter'}
                  </Text>
                </>
              )}
            </TouchableOpacity>
          </View>

          {/* Telemetry info */}
          <View style={styles.telemetryGrid}>
            <View style={styles.telemetryItem}>
              <Text style={styles.telemetryLabel}>Vision AI</Text>
              <Text style={styles.telemetryValue}>
                {system?.visionRunning ? `${system.visionFps.toFixed(1)} FPS` : 'Off'}
              </Text>
            </View>

            <View style={styles.telemetryItem}>
              <Text style={styles.telemetryLabel}>Last Person</Text>
              <Text style={styles.telemetryValue} numberOfLines={1}>
                {system?.lastPersonAt
                  ? new Date(system.lastPersonAt).toLocaleTimeString([], {
                      hour: '2-digit',
                      minute: '2-digit',
                    })
                  : 'None today'}
              </Text>
            </View>

            <View style={styles.telemetryItem}>
              <Text style={styles.telemetryLabel}>Lock Adapter</Text>
              <Text style={styles.telemetryValue}>{system?.lockAdapter || 'Mock'}</Text>
            </View>
          </View>
        </View>

        {/* Access & Smart Peripherals Card */}
        <View style={styles.card}>
          <Text style={styles.cardTitle}>Entrance & Lights</Text>

          {/* Lock Section */}
          <View style={styles.controlRow}>
            <View style={styles.controlInfo}>
              <View style={styles.iconCircleSmall}>
                <Ionicons
                  name={lock?.reachable === 'dead' ? 'cloud-offline-outline' : lock?.state === 'unlocked' ? 'lock-open' : 'lock-closed'}
                  size={20}
                  color={lock?.reachable === 'dead' ? '#9CA3AF' : lock?.state === 'unlocked' ? '#10B981' : '#F59E0B'}
                />
              </View>
              <View>
                <Text style={styles.controlTitle}>Front Door Lock</Text>
                <Text style={styles.controlSubtitle}>
                  {lock?.reachable === 'dead'
                    ? 'Not responding'
                    : `State: ${lock?.state || 'Unknown'}`}
                </Text>
              </View>
            </View>

            <View style={styles.controlButtonGroup}>
              <TouchableOpacity
                style={[styles.smallBtn, styles.btnLock]}
                onPress={handleLock}
                disabled={loadingAction !== null}
              >
                <Ionicons name="lock-closed" size={14} color="#FFF" />
                <Text style={styles.smallBtnText}>Lock</Text>
              </TouchableOpacity>

              <TouchableOpacity
                style={[styles.smallBtn, styles.btnUnlock]}
                onPress={handleUnlock}
                disabled={loadingAction !== null}
              >
                <Ionicons name="finger-print-outline" size={14} color="#FFF" />
                <Text style={styles.smallBtnText}>Unlock</Text>
              </TouchableOpacity>
            </View>
          </View>

          <View style={styles.divider} />

          {/* Zigbee Light Section */}
          <View style={styles.controlRow}>
            <View style={styles.controlInfo}>
              <View style={styles.iconCircleSmall}>
                <Ionicons name="bulb-outline" size={20} color="#FBBF24" />
              </View>
              <View>
                <Text style={styles.controlTitle}>Zigbee Smart Light</Text>
                <Text style={styles.controlSubtitle}>Porch / Living Room</Text>
              </View>
            </View>

            <View style={styles.controlButtonGroup}>
              <TouchableOpacity
                style={[styles.smallBtn, styles.btnLightOn]}
                onPress={() => handleLight(true)}
                disabled={loadingAction !== null}
              >
                <Ionicons name="sunny" size={14} color="#FBBF24" />
                <Text style={styles.smallBtnText}>On</Text>
              </TouchableOpacity>

              <TouchableOpacity
                style={[styles.smallBtn, styles.btnLightOff]}
                onPress={() => handleLight(false)}
                disabled={loadingAction !== null}
              >
                <Ionicons name="moon" size={14} color="#94A3B8" />
                <Text style={styles.smallBtnText}>Off</Text>
              </TouchableOpacity>
            </View>
          </View>

          {/* Pairing buttons */}
          <View style={styles.pairingRow}>
            <TouchableOpacity style={styles.linkButton} onPress={handlePairBulb}>
              <Ionicons name="bluetooth-outline" size={14} color="#60A5FA" />
              <Text style={styles.linkButtonText}>Pair Bulb</Text>
            </TouchableOpacity>

            <TouchableOpacity style={styles.linkButton} onPress={handlePairLock}>
              <Ionicons name="key-outline" size={14} color="#60A5FA" />
              <Text style={styles.linkButtonText}>Pair Lock</Text>
            </TouchableOpacity>
          </View>
        </View>

        <View style={styles.card}>
          <View style={styles.cardHeader}>
            <View style={styles.cardTitleRow}>
              <Ionicons name="checkbox-outline" size={20} color="#3B82F6" />
              <Text style={styles.cardTitle}>Tasks</Text>
            </View>
          </View>
          {tasks.length === 0 ? <Text style={styles.meetingText}>The list is empty.</Text> : null}
          {tasks.map((task) => (
            <View key={task.id} style={styles.controlRow}>
              <Text style={styles.meetingText}>
                {task.text}{task.due ? ` (${task.due})` : ''}
              </Text>
              <TouchableOpacity
                style={[styles.smallBtn, styles.btnLock]}
                onPress={() => handleDoneTask(task.id)}
                disabled={loadingAction !== null}
              >
                <Text style={styles.smallBtnText}>Done</Text>
              </TouchableOpacity>
            </View>
          ))}
          <TouchableOpacity
            style={[styles.smallBtn, styles.btnUnlock]}
            onPress={handlePrintTasks}
            disabled={loadingAction !== null || tasks.length === 0}
          >
            <Text style={styles.smallBtnText}>Print</Text>
          </TouchableOpacity>
        </View>

        <View style={styles.card}>
          <View style={styles.cardHeader}>
            <View style={styles.cardTitleRow}>
              <Ionicons name="mic-outline" size={20} color="#3B82F6" />
              <Text style={styles.cardTitle}>Meeting</Text>
            </View>
            <Text style={styles.controlSubtitle}>
              {meetingActive ? 'Recording' : 'Idle'}
            </Text>
          </View>
          <View style={styles.controlRow}>
            <TouchableOpacity
              style={[styles.smallBtn, styles.btnLock]}
              onPress={handleStartMeeting}
              disabled={loadingAction !== null || meetingActive}
            >
              <Text style={styles.smallBtnText}>Start</Text>
            </TouchableOpacity>
            <TouchableOpacity
              style={[styles.smallBtn, styles.btnUnlock]}
              onPress={handleStopMeeting}
              disabled={loadingAction !== null || !meetingActive}
            >
              <Text style={styles.smallBtnText}>Stop</Text>
            </TouchableOpacity>
          </View>
          {minutes ? (
            <View style={styles.meetingBody}>
              <Text style={styles.meetingTitle}>{minutes.title}</Text>
              {minutes.summary ? <Text style={styles.meetingText}>{minutes.summary}</Text> : null}
              {minutes.decisions.length > 0 ? (
                <Text style={styles.meetingLabel}>Decisions</Text>
              ) : null}
              {minutes.decisions.map((item) => (
                <Text key={item} style={styles.meetingText}>{item}</Text>
              ))}
              {minutes.actionItems.length > 0 ? (
                <Text style={styles.meetingLabel}>Action items</Text>
              ) : null}
              {minutes.actionItems.map((item) => (
                <Text key={item} style={styles.meetingText}>{item}</Text>
              ))}
            </View>
          ) : null}
        </View>

        {/* Live Camera Preview Card */}
        <View style={styles.card}>
          <View style={styles.cardHeader}>
            <View style={styles.cardTitleRow}>
              <Ionicons name="videocam-outline" size={20} color="#3B82F6" />
              <Text style={styles.cardTitle}>Live Cameras</Text>
            </View>
          </View>

          <View style={styles.camTabContainer}>
            <TouchableOpacity
              style={[
                styles.camTab,
                selectedCam === 'door' && styles.camTabActive,
              ]}
              onPress={() => setSelectedCam('door')}
            >
              <Ionicons
                name="home-outline"
                size={14}
                color={selectedCam === 'door' ? '#FFF' : '#94A3B8'}
              />
              <Text
                style={[
                  styles.camTabText,
                  selectedCam === 'door' && styles.camTabTextActive,
                ]}
              >
                Front Door (Doorbell)
              </Text>
            </TouchableOpacity>

            <TouchableOpacity
              style={[
                styles.camTab,
                selectedCam === 'driveway' && styles.camTabActive,
              ]}
              onPress={() => setSelectedCam('driveway')}
            >
              <Ionicons
                name="car-outline"
                size={14}
                color={selectedCam === 'driveway' ? '#FFF' : '#94A3B8'}
              />
              <Text
                style={[
                  styles.camTabText,
                  selectedCam === 'driveway' && styles.camTabTextActive,
                ]}
              >
                Driveway
              </Text>
            </TouchableOpacity>
          </View>

          <CameraLive camera={selectedCam} />
        </View>

        {/* Security Events & AI Smart Search */}
        <View style={styles.card}>
          <View style={styles.cardHeader}>
            <View style={styles.cardTitleRow}>
              <Ionicons name="time-outline" size={20} color="#38BDF8" />
              <Text style={styles.cardTitle}>Recent Security Events</Text>
            </View>
            <Text style={styles.eventCount}>{events.length} events</Text>
          </View>

          {/* Search Bar */}
          <View style={styles.searchBar}>
            <Ionicons name="search" size={18} color="#64748B" />
            <TextInput
              style={styles.searchInput}
              value={searchQuery}
              onChangeText={setSearchQuery}
              placeholder="Ask AI: 'person yesterday afternoon'..."
              placeholderTextColor="#64748B"
              returnKeyType="search"
              onSubmitEditing={handleSearch}
            />
            {searchQuery ? (
              <TouchableOpacity
                onPress={() => {
                  setSearchQuery('');
                  loadAllData();
                }}
              >
                <Ionicons name="close-circle" size={18} color="#64748B" />
              </TouchableOpacity>
            ) : null}
          </View>

          {searchUnderstood !== null && (
            <View style={styles.filterUnderstoodTag}>
              <Ionicons
                name={searchUnderstood ? 'checkmark-circle' : 'help-circle'}
                size={14}
                color={searchUnderstood ? '#10B981' : '#F59E0B'}
              />
              <Text style={styles.filterUnderstoodText}>
                {searchUnderstood
                  ? 'AI filtered by parsed intent'
                  : 'Showing standard event matches'}
              </Text>
            </View>
          )}

          {/* Events List */}
          {events.length === 0 ? (
            <View style={styles.emptyEvents}>
              <Ionicons name="checkmark-done-circle-outline" size={40} color="#475569" />
              <Text style={styles.emptyEventsText}>No security events recorded</Text>
            </View>
          ) : (
            <View style={styles.eventsList}>
              {events.map((item) => (
                <TouchableOpacity
                  key={item.id}
                  style={styles.eventItem}
                  onPress={() => setSelectedEvent(item)}
                >
                  <View style={styles.eventLeft}>
                    <View style={styles.eventIconCircle}>
                      <Ionicons name="person-outline" size={18} color="#60A5FA" />
                    </View>
                    <View>
                      <View style={styles.eventTitleRow}>
                        <Text style={styles.eventLabel}>{item.label}</Text>
                        {item.maskDetected && (
                          <View style={styles.maskBadge}>
                            <Text style={styles.maskBadgeText}>MASK</Text>
                          </View>
                        )}
                        <Text style={styles.eventConfidence}>
                          {(item.confidence * 100).toFixed(0)}%
                        </Text>
                      </View>
                      <Text style={styles.eventTimestamp}>{item.ts}</Text>
                    </View>
                  </View>

                  <View style={styles.eventRight}>
                    {item.snapshotUrl && (
                      <Ionicons name="image-outline" size={18} color="#94A3B8" />
                    )}
                    <Ionicons name="chevron-forward" size={16} color="#475569" />
                  </View>
                </TouchableOpacity>
              ))}
            </View>
          )}
        </View>
      </ScrollView>

      {/* Snapshot Modal */}
      <SnapshotModal
        visible={selectedEvent !== null}
        event={selectedEvent}
        onClose={() => setSelectedEvent(null)}
      />

      {/* Assistant Modal */}
      <AssistantModal
        visible={assistantVisible}
        onClose={() => setAssistantVisible(false)}
        onActionCompleted={loadAllData}
      />
    </SafeAreaView>
  );
};

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#0B0F19',
  },
  topBar: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: 20,
    paddingVertical: 12,
    borderBottomWidth: 1,
    borderBottomColor: '#1E293B',
  },
  brandContainer: {
    gap: 2,
  },
  brandTitle: {
    fontSize: 20,
    fontWeight: '700',
    color: '#F8FAFC',
    letterSpacing: 0.3,
  },
  networkBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
  },
  networkDot: {
    width: 8,
    height: 8,
    borderRadius: 4,
  },
  dotGreen: {
    backgroundColor: '#10B981',
  },
  dotOrange: {
    backgroundColor: '#F59E0B',
  },
  networkText: {
    fontSize: 12,
    color: '#94A3B8',
    fontWeight: '500',
  },
  headerActions: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
  },
  aiButton: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
    backgroundColor: 'rgba(56, 189, 248, 0.15)',
    borderWidth: 1,
    borderColor: 'rgba(56, 189, 248, 0.3)',
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: 16,
  },
  aiButtonText: {
    color: '#38BDF8',
    fontWeight: '600',
    fontSize: 13,
  },
  iconButton: {
    width: 36,
    height: 36,
    borderRadius: 18,
    backgroundColor: '#161E2E',
    borderWidth: 1,
    borderColor: '#1E293B',
    alignItems: 'center',
    justifyContent: 'center',
  },
  scrollArea: {
    padding: 16,
    gap: 16,
  },
  card: {
    backgroundColor: '#161E2E',
    borderRadius: 18,
    padding: 18,
    borderWidth: 1,
    borderColor: '#1E293B',
  },
  cardHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 14,
  },
  cardTitleRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
  },
  cardTitle: {
    fontSize: 16,
    fontWeight: '700',
    color: '#F8FAFC',
  },
  statusBadge: {
    paddingHorizontal: 10,
    paddingVertical: 4,
    borderRadius: 8,
  },
  badgeArmed: {
    backgroundColor: 'rgba(239, 68, 68, 0.15)',
  },
  badgeDisarmed: {
    backgroundColor: 'rgba(16, 185, 129, 0.15)',
  },
  statusBadgeText: {
    fontSize: 12,
    fontWeight: '700',
    letterSpacing: 0.5,
  },
  textArmed: {
    color: '#EF4444',
  },
  textDisarmed: {
    color: '#10B981',
  },
  alarmAlertBox: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    backgroundColor: 'rgba(239, 68, 68, 0.15)',
    borderWidth: 1,
    borderColor: '#EF4444',
    padding: 12,
    borderRadius: 12,
    marginBottom: 14,
  },
  alarmAlertText: {
    color: '#EF4444',
    fontWeight: '700',
    fontSize: 13,
    flex: 1,
  },
  armButtonGroup: {
    marginBottom: 16,
  },
  actionBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 8,
    paddingVertical: 14,
    borderRadius: 12,
  },
  btnArmedActive: {
    backgroundColor: '#2563EB',
  },
  btnInactive: {
    backgroundColor: '#1E293B',
    borderWidth: 1,
    borderColor: '#334155',
  },
  actionBtnText: {
    color: '#FFF',
    fontWeight: '600',
    fontSize: 15,
  },
  telemetryGrid: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    backgroundColor: '#0F172A',
    borderRadius: 12,
    padding: 12,
  },
  telemetryItem: {
    flex: 1,
    alignItems: 'center',
  },
  telemetryLabel: {
    fontSize: 11,
    color: '#64748B',
    marginBottom: 2,
  },
  telemetryValue: {
    fontSize: 13,
    fontWeight: '600',
    color: '#E2E8F0',
  },
  controlRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginVertical: 6,
  },
  controlInfo: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
  },
  iconCircleSmall: {
    width: 40,
    height: 40,
    borderRadius: 20,
    backgroundColor: '#0F172A',
    alignItems: 'center',
    justifyContent: 'center',
    borderWidth: 1,
    borderColor: '#1E293B',
  },
  controlTitle: {
    fontSize: 15,
    fontWeight: '600',
    color: '#F8FAFC',
  },
  controlSubtitle: {
    fontSize: 12,
    color: '#94A3B8',
    marginTop: 2,
  },
  controlButtonGroup: {
    flexDirection: 'row',
    gap: 8,
  },
  smallBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
    paddingVertical: 8,
    paddingHorizontal: 12,
    borderRadius: 8,
  },
  meetingBody: {
    marginTop: 12,
    gap: 4,
  },
  meetingTitle: {
    color: '#F8FAFC',
    fontSize: 15,
    fontWeight: '700',
  },
  meetingLabel: {
    color: '#93C5FD',
    fontSize: 12,
    fontWeight: '700',
    marginTop: 8,
  },
  meetingText: {
    color: '#CBD5E1',
    fontSize: 13,
    lineHeight: 18,
  },
  smallBtnText: {
    color: '#FFF',
    fontSize: 13,
    fontWeight: '600',
  },
  btnLock: {
    backgroundColor: '#1E293B',
    borderWidth: 1,
    borderColor: '#334155',
  },
  btnUnlock: {
    backgroundColor: '#059669',
  },
  btnLightOn: {
    backgroundColor: '#D97706',
  },
  btnLightOff: {
    backgroundColor: '#1E293B',
    borderWidth: 1,
    borderColor: '#334155',
  },
  divider: {
    height: 1,
    backgroundColor: '#1E293B',
    marginVertical: 12,
  },
  pairingRow: {
    flexDirection: 'row',
    justifyContent: 'flex-end',
    gap: 16,
    marginTop: 10,
  },
  linkButton: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
  },
  linkButtonText: {
    fontSize: 12,
    color: '#60A5FA',
  },
  camTabContainer: {
    flexDirection: 'row',
    backgroundColor: '#0F172A',
    borderRadius: 10,
    padding: 4,
    marginBottom: 12,
    borderWidth: 1,
    borderColor: '#1E293B',
    gap: 4,
  },
  camTab: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 6,
    paddingVertical: 8,
    borderRadius: 8,
  },
  camTabActive: {
    backgroundColor: '#2563EB',
  },
  camTabText: {
    fontSize: 12,
    fontWeight: '500',
    color: '#94A3B8',
  },
  camTabTextActive: {
    color: '#FFF',
    fontWeight: '700',
  },
  cameraBox: {
    height: 190,
    borderRadius: 12,
    overflow: 'hidden',
    backgroundColor: '#000',
    position: 'relative',
  },
  cameraImage: {
    width: '100%',
    height: '100%',
  },
  cameraPlaceholder: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    gap: 8,
  },
  cameraPlaceholderText: {
    color: '#64748B',
    fontSize: 13,
  },
  tapToRefreshText: {
    color: '#38BDF8',
    fontSize: 11,
    fontWeight: '600',
  },
  cameraLoadingOverlay: {
    ...StyleSheet.absoluteFill,
    backgroundColor: 'rgba(0, 0, 0, 0.4)',
    alignItems: 'center',
    justifyContent: 'center',
  },
  cameraOverlayTag: {
    position: 'absolute',
    top: 10,
    left: 10,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    backgroundColor: 'rgba(0, 0, 0, 0.6)',
    paddingHorizontal: 8,
    paddingVertical: 4,
    borderRadius: 6,
  },
  redLiveDot: {
    width: 6,
    height: 6,
    borderRadius: 3,
    backgroundColor: '#EF4444',
  },
  cameraOverlayText: {
    color: '#FFF',
    fontSize: 10,
    fontWeight: '700',
  },
  eventCount: {
    fontSize: 12,
    color: '#64748B',
  },
  searchBar: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#0F172A',
    borderRadius: 10,
    paddingHorizontal: 12,
    paddingVertical: 10,
    borderWidth: 1,
    borderColor: '#334155',
    gap: 8,
    marginBottom: 10,
  },
  searchInput: {
    flex: 1,
    color: '#F8FAFC',
    fontSize: 14,
  },
  filterUnderstoodTag: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    marginBottom: 12,
  },
  filterUnderstoodText: {
    fontSize: 12,
    color: '#94A3B8',
  },
  emptyEvents: {
    alignItems: 'center',
    paddingVertical: 24,
    gap: 8,
  },
  emptyEventsText: {
    color: '#64748B',
    fontSize: 14,
  },
  eventsList: {
    gap: 8,
  },
  eventItem: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    backgroundColor: '#0F172A',
    padding: 12,
    borderRadius: 10,
    borderWidth: 1,
    borderColor: '#1E293B',
  },
  eventLeft: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
  },
  eventIconCircle: {
    width: 36,
    height: 36,
    borderRadius: 18,
    backgroundColor: 'rgba(96, 165, 250, 0.1)',
    alignItems: 'center',
    justifyContent: 'center',
  },
  eventTitleRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
  },
  maskBadge: {
    backgroundColor: 'rgba(239, 68, 68, 0.2)',
    borderColor: '#EF4444',
    borderWidth: 1,
    borderRadius: 4,
    paddingHorizontal: 5,
    paddingVertical: 1,
  },
  maskBadgeText: {
    color: '#F87171',
    fontSize: 10,
    fontWeight: '700',
    letterSpacing: 0.5,
  },
  eventLabel: {
    fontSize: 14,
    fontWeight: '600',
    color: '#F8FAFC',
    textTransform: 'capitalize',
  },
  eventConfidence: {
    fontSize: 12,
    color: '#60A5FA',
    fontWeight: '500',
  },
  eventTimestamp: {
    fontSize: 11,
    color: '#64748B',
    marginTop: 2,
  },
  eventRight: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
  },
});
