import Constants, { ExecutionEnvironment } from 'expo-constants';
import { Platform } from 'react-native';

import { settingApi } from './api/setting';
import { tokenStore } from './api/token-store';

// Registers this device's Expo push token with our API. Fails silently: push is optional,
// and is unavailable on web, simulators without credentials, and Expo Go on Android.
export async function registerPushToken(): Promise<void> {
  if (Platform.OS !== 'ios' && Platform.OS !== 'android') return;
  if (Platform.OS === 'android' && Constants.executionEnvironment === ExecutionEnvironment.StoreClient) return;

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
