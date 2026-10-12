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
}

export const SnapshotModal: React.FC<SnapshotModalProps> = ({ event, visible, onClose }) => {
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

  if (!event) return null;

  return (
    <Modal visible={visible} animationType="slide" transparent={false} onRequestClose={onClose}>
      <SafeAreaView style={styles.container}>
        <View style={styles.header}>
          <View>
            <Text style={styles.title}>Event Snapshot</Text>
            <Text style={styles.timestamp}>{event.ts}</Text>
          </View>
          <TouchableOpacity style={styles.closeButton} onPress={onClose}>
            <Ionicons name="close" size={24} color="#FFF" />
          </TouchableOpacity>
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
});
