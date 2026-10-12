import * as LocalAuthentication from 'expo-local-authentication';
import { Alert, Platform } from 'react-native';
import { SessionStore } from '../storage/sessionStore';

export class UnlockHelper {
  static async confirmUnlock(onConfirmed: () => void): Promise<void> {
    try {
      const hasHardware = await LocalAuthentication.hasHardwareAsync();
      const isEnrolled = await LocalAuthentication.isEnrolledAsync();

      if (hasHardware && isEnrolled) {
        const result = await LocalAuthentication.authenticateAsync({
          promptMessage: 'Unlock Smart Door Lock',
          fallbackLabel: 'Enter PIN',
          cancelLabel: 'Cancel',
          disableDeviceFallback: false,
        });

        if (result.success) {
          onConfirmed();
          return;
        }

        // If user cancelled, don't show further alerts
        if (result.error === 'user_cancel' || result.error === 'app_cancel') {
          return;
        }
      }
    } catch (e) {
      // Local authentication failure or error, fall through to PIN fallback
    }

    // Fallback: PIN verification
    UnlockHelper.promptPin(onConfirmed);
  }

  private static async promptPin(onConfirmed: () => void): Promise<void> {
    const expectedPin = await SessionStore.getStationPin();

    if (Platform.OS === 'ios' && Alert.prompt) {
      Alert.prompt(
        'Unlock Door',
        'Biometric authentication unavailable. Enter PIN to confirm:',
        [
          { text: 'Cancel', style: 'cancel' },
          {
            text: 'Unlock',
            onPress: (pin?: string) => {
              if (pin === expectedPin) {
                onConfirmed();
              } else {
                Alert.alert('Access Denied', 'PIN does not match.');
              }
            },
          },
        ],
        'secure-text'
      );
    } else {
      // Direct confirm if prompt is unsupported
      Alert.alert(
        'Unlock Door?',
        'Confirm you want to unlock the entrance door now.',
        [
          { text: 'Cancel', style: 'cancel' },
          { text: 'Unlock Now', style: 'destructive', onPress: onConfirmed },
        ]
      );
    }
  }
}
