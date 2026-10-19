import React, { useEffect, useState } from 'react';
import {
  Modal,
  View,
  Text,
  Image,
  TouchableOpacity,
  StyleSheet,
  ActivityIndicator,
  SafeAreaView,
  Dimensions,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { DoorEvent } from '../types/models';
import { HubClient } from '../api/hubClient';
import { SessionStore } from '../storage/sessionStore';

interface SnapshotModalProps {
  event: DoorEvent | null;
  visible: boolean;
  onClose: () => void;
  embedded?: boolean;
}

export const SnapshotModal: React.FC<SnapshotModalProps> = ({
  event,
  visible,
  onClose,
  embedded = false,
}) => {
  const [imageUrl, setImageUrl] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [token, setToken] = useState<string>('');

  useEffect(() => {
    SessionStore.getAccessToken().then((t) => setToken(t || ''));
  }, []);

  useEffect(() => {
    if (visible && event?.snapshotUrl) {
      setLoading(true);
      HubClient.getEventSnapshotUrl(event.snapshotUrl).then((url) => {
        setImageUrl(url);
      });
    } else {
      setImageUrl(null);
    }
  }, [visible, event]);

  if (!event || (embedded && !visible)) return null;

  const body = (
      <SafeAreaView style={styles.container}>
        <View style={styles.header}>
          {embedded ? (
            <TouchableOpacity style={styles.backButton} onPress={onClose}>
              <Ionicons name="chevron-back" size={22} color="#FFF" />
              <Text style={styles.backText}>AI Assistant</Text>
            </TouchableOpacity>
          ) : (
            <>
              <View>
                <Text style={styles.title}>Event Snapshot</Text>
                <Text style={styles.timestamp}>{event.ts}</Text>
              </View>
              <TouchableOpacity style={styles.closeButton} onPress={onClose}>
                <Ionicons name="close" size={24} color="#FFF" />
              </TouchableOpacity>
            </>
          )}
        </View>

        <View style={styles.imageContainer}>
          {imageUrl ? (
            <Image
              source={{
                uri: imageUrl,
                headers: token ? { Authorization: `Bearer ${token}` } : undefined,
              }}
              style={styles.image}
              resizeMode="contain"
              onLoadStart={() => setLoading(true)}
              onLoadEnd={() => setLoading(false)}
            />
          ) : (
            <View style={styles.noImage}>
              <Ionicons name="image-outline" size={48} color="#64748B" />
              <Text style={styles.noImageText}>Snapshot unavailable</Text>
            </View>
          )}

          {loading && (
            <View style={styles.loadingOverlay}>
              <ActivityIndicator size="large" color="#3B82F6" />
            </View>
          )}
        </View>

        <View style={styles.detailsCard}>
          <View style={styles.detailRow}>
            <Text style={styles.detailLabel}>Detected Label</Text>
            <View style={styles.badge}>
              <Ionicons name="person" size={14} color="#60A5FA" />
              <Text style={styles.badgeText}>{event.label}</Text>
            </View>
          </View>

          <View style={styles.detailRow}>
            <Text style={styles.detailLabel}>Face Mask</Text>
            <View
              style={[
                styles.badge,
                event.maskDetected ? styles.maskBadgeAlert : styles.maskBadgeClear,
              ]}
            >
              <Text
                style={[
                  styles.badgeText,
                  event.maskDetected ? styles.maskTextAlert : styles.maskTextClear,
                ]}
              >
                {event.maskDetected ? '⚠️ Detected (Covered)' : 'None (Unmasked)'}
              </Text>
            </View>
          </View>

          <View style={styles.detailRow}>
            <Text style={styles.detailLabel}>AI Confidence</Text>
            <Text style={styles.detailValue}>{(event.confidence * 100).toFixed(1)}%</Text>
          </View>

          {event.camera && (
            <View style={styles.detailRow}>
              <Text style={styles.detailLabel}>Camera Source</Text>
              <Text style={styles.detailValue}>{event.camera}</Text>
            </View>
          )}
        </View>
      </SafeAreaView>
  );

  if (embedded) {
    return <View style={styles.embedded}>{body}</View>;
  }

  return (
    <Modal visible={visible} animationType="slide" transparent={false} onRequestClose={onClose}>
      {body}
    </Modal>
  );
};

const { width } = Dimensions.get('window');

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#0B0F19',
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: 20,
    paddingVertical: 14,
    borderBottomWidth: 1,
    borderBottomColor: '#1E293B',
  },
  title: {
    fontSize: 18,
    fontWeight: '700',
    color: '#F8FAFC',
  },
  timestamp: {
    fontSize: 12,
    color: '#94A3B8',
    marginTop: 2,
  },
  backButton: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
  },
  backText: {
    fontSize: 17,
    fontWeight: '600',
    color: '#F8FAFC',
  },
  embedded: {
    ...StyleSheet.absoluteFill,
    zIndex: 20,
    backgroundColor: '#0B0F19',
  },
  closeButton: {
    width: 36,
    height: 36,
    borderRadius: 18,
    backgroundColor: '#1E293B',
    alignItems: 'center',
    justifyContent: 'center',
  },
  imageContainer: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    backgroundColor: '#000',
  },
  image: {
    width: width,
    height: '100%',
  },
  noImage: {
    alignItems: 'center',
    gap: 8,
  },
  noImageText: {
    color: '#64748B',
    fontSize: 14,
  },
  loadingOverlay: {
    ...StyleSheet.absoluteFill,
    backgroundColor: 'rgba(11, 15, 25, 0.7)',
    justifyContent: 'center',
    alignItems: 'center',
  },
  detailsCard: {
    backgroundColor: '#161E2E',
    borderTopWidth: 1,
    borderTopColor: '#1E293B',
    padding: 20,
    gap: 12,
  },
  detailRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  detailLabel: {
    fontSize: 14,
    color: '#94A3B8',
  },
  detailValue: {
    fontSize: 14,
    fontWeight: '600',
    color: '#F8FAFC',
  },
  badge: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    backgroundColor: 'rgba(59, 130, 246, 0.15)',
    paddingHorizontal: 10,
    paddingVertical: 4,
    borderRadius: 8,
  },
  badgeText: {
    fontSize: 13,
    fontWeight: '600',
    color: '#60A5FA',
    textTransform: 'capitalize',
  },
  maskBadgeAlert: {
    backgroundColor: 'rgba(239, 68, 68, 0.2)',
  },
  maskBadgeClear: {
    backgroundColor: 'rgba(34, 197, 94, 0.15)',
  },
  maskTextAlert: {
    color: '#F87171',
    textTransform: 'none',
  },
  maskTextClear: {
    color: '#4ADE80',
    textTransform: 'none',
  },
});
