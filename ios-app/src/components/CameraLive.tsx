import React, { useEffect, useState } from 'react';
import { ActivityIndicator, Image, StyleSheet, Text, View } from 'react-native';
import { HubClient } from '../api/hubClient';

type CameraName = 'door' | 'driveway';

function jpegDataUri(data: unknown): string | null {
  if (typeof data === 'string' && data.length > 16) {
    if (data.startsWith('data:')) return data;
    if (data.charCodeAt(0) === 0xff && data.charCodeAt(1) === 0xd8) {
      return `data:image/jpeg;base64,${btoa(data)}`;
    }
    return `data:image/jpeg;base64,${data}`;
  }
  if (data instanceof ArrayBuffer) {
    const bytes = new Uint8Array(data);
    let binary = '';
    const step = 0x8000;
    for (let index = 0; index < bytes.length; index += step) {
      binary += String.fromCharCode(...bytes.subarray(index, index + step));
    }
    return `data:image/jpeg;base64,${btoa(binary)}`;
  }
  return null;
}

export const CameraLive: React.FC<{ camera: CameraName }> = ({ camera }) => {
  const [uri, setUri] = useState<string | null>(null);
  const [status, setStatus] = useState<'connecting' | 'live' | 'offline'>('connecting');

  useEffect(() => {
    let socket: WebSocket | null = null;
    let reconnect: ReturnType<typeof setTimeout> | null = null;
    let closed = false;

    const connect = async () => {
      if (closed) return;
      setStatus((current) => (current === 'live' ? current : 'connecting'));
      try {
        const url = await HubClient.getCameraLiveUrl(camera);
        const ws = new WebSocket(url);
        socket = ws;
        ws.onmessage = (event) => {
          if (closed) return;
          const show = (next: string | null) => {
            if (!next || closed) return;
            setUri(next);
            setStatus('live');
          };
          const payload = event.data;
          if (typeof Blob !== 'undefined' && payload instanceof Blob) {
            payload.arrayBuffer().then((buffer) => show(jpegDataUri(buffer)));
            return;
          }
          show(jpegDataUri(payload));
        };
        ws.onclose = () => {
          if (closed) return;
          setStatus((current) => (current === 'live' ? 'offline' : current));
          reconnect = setTimeout(connect, 2000);
        };
        ws.onerror = () => {
          if (!closed) setStatus((current) => (current === 'live' ? current : 'offline'));
        };
      } catch {
        if (!closed) {
          setStatus('offline');
          reconnect = setTimeout(connect, 2000);
        }
      }
    };

    setUri(null);
    setStatus('connecting');
    connect();
    return () => {
      closed = true;
      if (reconnect) clearTimeout(reconnect);
      socket?.close();
    };
  }, [camera]);

  return (
    <View style={styles.box}>
      {uri ? (
        <Image source={{ uri }} style={styles.image} resizeMode="cover" />
      ) : (
        <View style={styles.placeholder}>
          {status === 'connecting' ? (
            <ActivityIndicator size="small" color="#38BDF8" />
          ) : null}
          <Text style={styles.placeholderText}>
            {status === 'offline' ? 'Camera stream reconnecting' : 'Opening camera stream'}
          </Text>
        </View>
      )}
      <View style={styles.tag}>
        <View style={[styles.dot, status === 'live' && styles.dotLive]} />
        <Text style={styles.tagText}>
          {camera === 'door' ? 'CAM 01 · FRONT DOOR' : 'CAM 02 · DRIVEWAY'}
          {status === 'live' ? ' · LIVE' : ''}
        </Text>
      </View>
    </View>
  );
};

const styles = StyleSheet.create({
  box: {
    height: 220,
    borderRadius: 12,
    overflow: 'hidden',
    backgroundColor: '#0F172A',
    borderWidth: 1,
    borderColor: '#1E293B',
  },
  image: {
    width: '100%',
    height: '100%',
  },
  placeholder: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    gap: 8,
  },
  placeholderText: {
    color: '#64748B',
    fontSize: 13,
  },
  tag: {
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
  dot: {
    width: 6,
    height: 6,
    borderRadius: 3,
    backgroundColor: '#64748B',
  },
  dotLive: {
    backgroundColor: '#EF4444',
  },
  tagText: {
    color: '#FFF',
    fontSize: 10,
    fontWeight: '700',
  },
});
