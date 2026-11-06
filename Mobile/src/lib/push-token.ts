import Constants, { ExecutionEnvironment } from 'expo-constants';
import { Platform } from 'react-native';

import { settingApi } from './api/setting';
import { tokenStore } from './api/token-store';

/** Push is unavailable on web and in Expo Go on Android. */
function pushSupported(): boolean {
  if (Platform.OS !== 'ios' && Platform.OS !== 'android') return false;
  return !(Platform.OS === 'android' && Constants.executionEnvironment === ExecutionEnvironment.StoreClient);
}

// Registers this device's Expo push token with our API. Fails silently: push is optional,
// and is unavailable on web, simulators without credentials, and Expo Go on Android. A token still
// registered to another signed-in account is refused by the server (409) and skipped here.
export async function registerPushToken(): Promise<void> {
  if (!pushSupported()) return;

  try {
    const Notifications = await import('expo-notifications');
    let { status } = await Notifications.getPermissionsAsync();
    if (status !== 'granted') status = (await Notifications.requestPermissionsAsync()).status;
    if (status !== 'granted') return;

    const projectId = Constants.expoConfig?.extra?.eas?.projectId ?? Constants.easConfig?.projectId;
    const { data: token } = await Notifications.getExpoPushTokenAsync(projectId ? { projectId } : undefined);

    const saved = await settingApi.registerPushToken({
      token,
      platform: Platform.OS === 'ios' ? 'IOS' : 'ANDROID',
      device_label: Constants.deviceName ?? null,
    });
    await tokenStore.setPushTokenId(saved.id);
  } catch (err) {
    if (__DEV__) console.warn('[push] registration skipped:', err instanceof Error ? err.message : err);
  }
}

// Removes this device's push token from the server (call while still authenticated).
export async function unregisterPushToken(): Promise<void> {
  try {
    const id = await tokenStore.getPushTokenId();
    if (id) await settingApi.deletePushToken(id);
  } catch {
    // best effort; server-side cascade/ownership rules still apply
  }
}

/**
 * While signed in: shows pushes that arrive in the foreground, re-registers when the OS rotates the
 * push token, and calls `onOpen` when the caregiver taps a notification. Returns the cleanup.
 */
export function watchPushNotifications(onOpen: () => void): () => void {
  if (!pushSupported()) return () => undefined;
  let stopped = false;
  let subscriptions: { remove: () => void }[] = [];
  import('expo-notifications')
    .then((Notifications) => {
      if (stopped) return;
      Notifications.setNotificationHandler({
        handleNotification: async () => ({
          shouldShowBanner: true,
          shouldShowList: true,
          shouldPlaySound: true,
          shouldSetBadge: false,
        }),
      });
      subscriptions = [
        // The listener carries the native device token; the Expo token is derived from it again.
        Notifications.addPushTokenListener(() => void registerPushToken()),
        Notifications.addNotificationResponseReceivedListener(() => onOpen()),
      ];
    })
    .catch((err: unknown) => {
      if (__DEV__) console.warn('[push] listeners skipped:', err instanceof Error ? err.message : err);
    });
  return () => {
    stopped = true;
    subscriptions.forEach((s) => s.remove());
    subscriptions = [];
  };
}
