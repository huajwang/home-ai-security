import React, { useState, useEffect } from 'react';
import {
  View,
  Text,
  TextInput,
  TouchableOpacity,
  StyleSheet,
  ActivityIndicator,
  Alert,
  KeyboardAvoidingView,
  Platform,
  ScrollView,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { HubClient } from '../api/hubClient';
import {
  SessionStore,
  DEFAULT_HUB_URL,
  TAILSCALE_DOMAIN_HTTPS_URL,
  TAILSCALE_HTTP_URL,
  LAN_HTTP_URL,
} from '../storage/sessionStore';

interface LoginScreenProps {
  onLoginSuccess: () => void;
}

export const LoginScreen: React.FC<LoginScreenProps> = ({ onLoginSuccess }) => {
  const [hubUrl, setHubUrlState] = useState(DEFAULT_HUB_URL);
  const [username, setUsername] = useState('owner');
  const [password, setPassword] = useState('changeme');
  const [deviceName, setDeviceName] = useState('iPhone');
  const [cloudUrl, setCloudUrl] = useState('');
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    SessionStore.getHubUrl().then((url) => {
      if (url) setHubUrlState(url);
    });
    SessionStore.getCloudLinkUrl().then((url) => {
      if (url) setCloudUrl(url);
    });
  }, []);

  const handleLogin = async () => {
    if (!hubUrl.trim()) {
      Alert.alert('Configuration Error', 'Please enter a valid Hub URL.');
      return;
    }
    if (!username.trim() || !password) {
      Alert.alert('Validation Error', 'Please enter both username and password.');
      return;
    }

    setLoading(true);
    try {
      await SessionStore.setHubUrl(hubUrl);
      await HubClient.login(username.trim(), password, deviceName.trim(), 'phone');
      onLoginSuccess();
    } catch (err: any) {
      Alert.alert('Sign In Failed', err?.message || 'Could not connect to the hub.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <KeyboardAvoidingView
      style={styles.container}
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}
    >
      <ScrollView contentContainerStyle={styles.scrollContent} keyboardShouldPersistTaps="handled">
        <View style={styles.header}>
          <View style={styles.iconCircle}>
            <Ionicons name="shield-checkmark" size={44} color="#3B82F6" />
          </View>
          <Text style={styles.title}>Home AI Security</Text>
          <Text style={styles.subtitle}>iOS Edge Hub Client</Text>
        </View>

        <View style={styles.card}>
          <Text style={styles.cardTitle}>Hub Connection</Text>

          <Text style={styles.label}>Hub URL</Text>
          <TextInput
            style={styles.input}
            value={hubUrl}
            onChangeText={setHubUrlState}
            placeholder="https://100.87.220.55:8443"
            placeholderTextColor="#64748B"
            autoCapitalize="none"
            autoCorrect={false}
            keyboardType="url"
          />

          <View style={styles.quickPills}>
            <TouchableOpacity
              style={[
                styles.pill,
                hubUrl === TAILSCALE_DOMAIN_HTTPS_URL && styles.pillActive,
              ]}
              onPress={() => setHubUrlState(TAILSCALE_DOMAIN_HTTPS_URL)}
            >
              <Ionicons
                name="shield-checkmark"
                size={14}
                color={hubUrl === TAILSCALE_DOMAIN_HTTPS_URL ? '#10B981' : '#94A3B8'}
              />
              <Text style={[styles.pillText, hubUrl === TAILSCALE_DOMAIN_HTTPS_URL && styles.pillTextActive]}>
                Tailscale HTTPS (Official Let's Encrypt Cert)
              </Text>
            </TouchableOpacity>

            <TouchableOpacity
              style={[
                styles.pill,
                hubUrl === TAILSCALE_HTTP_URL && styles.pillActive,
              ]}
              onPress={() => setHubUrlState(TAILSCALE_HTTP_URL)}
            >
              <Ionicons
                name="globe-outline"
                size={14}
                color={hubUrl === TAILSCALE_HTTP_URL ? '#60A5FA' : '#94A3B8'}
              />
              <Text style={[styles.pillText, hubUrl === TAILSCALE_HTTP_URL && styles.pillTextActive]}>
                Tailscale HTTP (IP: 100.87.220.55:8080)
              </Text>
            </TouchableOpacity>

            <TouchableOpacity
              style={[
                styles.pill,
                hubUrl === LAN_HTTP_URL && styles.pillActive,
              ]}
              onPress={() => setHubUrlState(LAN_HTTP_URL)}
            >
              <Ionicons
                name="wifi-outline"
                size={14}
                color={hubUrl === LAN_HTTP_URL ? '#10B981' : '#94A3B8'}
              />
              <Text style={[styles.pillText, hubUrl === LAN_HTTP_URL && styles.pillTextActive]}>
                Home Wi-Fi LAN (10.0.0.83:8080)
              </Text>
            </TouchableOpacity>

            {cloudUrl ? (
              <TouchableOpacity
                style={[styles.pill, hubUrl === cloudUrl && styles.pillActive]}
                onPress={() => setHubUrlState(cloudUrl)}
              >
                <Ionicons
                  name="cloud-outline"
                  size={14}
                  color={hubUrl === cloudUrl ? '#38BDF8' : '#94A3B8'}
                />
                <Text style={[styles.pillText, hubUrl === cloudUrl && styles.pillTextActive]}>
                  Cloud Link ({cloudUrl.replace(/^https?:\/\//, '')})
                </Text>
              </TouchableOpacity>
            ) : null}
          </View>

          <View style={styles.divider} />

          <Text style={styles.label}>Username</Text>
          <TextInput
            style={styles.input}
            value={username}
            onChangeText={setUsername}
            placeholder="owner"
            placeholderTextColor="#64748B"
            autoCapitalize="none"
          />

          <Text style={styles.label}>Password</Text>
          <TextInput
            style={styles.input}
            value={password}
            onChangeText={setPassword}
            placeholder="Password"
            placeholderTextColor="#64748B"
            secureTextEntry
          />

          <Text style={styles.label}>Device Name</Text>
          <TextInput
            style={styles.input}
            value={deviceName}
            onChangeText={setDeviceName}
            placeholder="iPhone"
            placeholderTextColor="#64748B"
          />

          <TouchableOpacity
            style={[styles.loginButton, loading && styles.buttonDisabled]}
            onPress={handleLogin}
            disabled={loading}
          >
            {loading ? (
              <ActivityIndicator color="#FFF" />
            ) : (
              <>
                <Text style={styles.loginButtonText}>Connect & Sign In</Text>
                <Ionicons name="arrow-forward" size={18} color="#FFF" />
              </>
            )}
          </TouchableOpacity>
        </View>

        <View style={styles.infoBox}>
          <Ionicons name="information-circle-outline" size={18} color="#3B82F6" />
          <Text style={styles.infoText}>
            Over Tailscale, your iPhone connects directly to the ROCK 5T edge hub with end-to-end WireGuard encryption.
          </Text>
        </View>
      </ScrollView>
    </KeyboardAvoidingView>
  );
};

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#0B0F19',
  },
  scrollContent: {
    flexGrow: 1,
    justifyContent: 'center',
    padding: 24,
  },
  header: {
    alignItems: 'center',
    marginBottom: 32,
  },
  iconCircle: {
    width: 80,
    height: 80,
    borderRadius: 40,
    backgroundColor: 'rgba(59, 130, 246, 0.15)',
    borderWidth: 1,
    borderColor: 'rgba(59, 130, 246, 0.3)',
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: 16,
  },
  title: {
    fontSize: 26,
    fontWeight: '700',
    color: '#F8FAFC',
    letterSpacing: 0.5,
  },
  subtitle: {
    fontSize: 14,
    color: '#94A3B8',
    marginTop: 4,
  },
  card: {
    backgroundColor: '#161E2E',
    borderRadius: 20,
    padding: 24,
    borderWidth: 1,
    borderColor: '#1E293B',
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 10 },
    shadowOpacity: 0.3,
    shadowRadius: 20,
  },
  cardTitle: {
    fontSize: 18,
    fontWeight: '600',
    color: '#E2E8F0',
    marginBottom: 16,
  },
  label: {
    fontSize: 13,
    fontWeight: '500',
    color: '#94A3B8',
    marginBottom: 6,
    marginTop: 12,
  },
  input: {
    backgroundColor: '#0F172A',
    borderWidth: 1,
    borderColor: '#334155',
    borderRadius: 12,
    paddingHorizontal: 14,
    paddingVertical: 12,
    color: '#F8FAFC',
    fontSize: 15,
  },
  quickPills: {
    flexDirection: 'column',
    gap: 8,
    marginTop: 10,
  },
  pill: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    backgroundColor: '#0F172A',
    paddingVertical: 8,
    paddingHorizontal: 12,
    borderRadius: 10,
    borderWidth: 1,
    borderColor: '#334155',
  },
  pillActive: {
    backgroundColor: 'rgba(59, 130, 246, 0.2)',
    borderColor: '#3B82F6',
  },
  pillText: {
    fontSize: 12,
    color: '#94A3B8',
  },
  pillTextActive: {
    color: '#60A5FA',
    fontWeight: '600',
  },
  divider: {
    height: 1,
    backgroundColor: '#1E293B',
    marginVertical: 14,
  },
  loginButton: {
    backgroundColor: '#2563EB',
    borderRadius: 12,
    paddingVertical: 14,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 8,
    marginTop: 24,
  },
  buttonDisabled: {
    opacity: 0.6,
  },
  loginButtonText: {
    color: '#FFF',
    fontSize: 16,
    fontWeight: '600',
  },
  infoBox: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: 'rgba(59, 130, 246, 0.1)',
    borderRadius: 12,
    padding: 14,
    marginTop: 24,
    gap: 10,
    borderWidth: 1,
    borderColor: 'rgba(59, 130, 246, 0.2)',
  },
  infoText: {
    flex: 1,
    fontSize: 12,
    color: '#93C5FD',
    lineHeight: 18,
  },
});
