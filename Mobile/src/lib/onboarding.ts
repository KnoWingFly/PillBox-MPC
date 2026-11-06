// Whether this phone has finished the onboarding slides. Not a secret, so AsyncStorage.
// One small store so the root navigator and the screens read the same value without a context.
import AsyncStorage from '@react-native-async-storage/async-storage';
import { useEffect, useSyncExternalStore } from 'react';

const SEEN_KEY = 'pillcare.onboarding_seen';
const SEEN_VALUE = '1';

export type OnboardingState = 'loading' | 'seen' | 'unseen';

let state: OnboardingState = 'loading';
let loadStarted = false;
const listeners = new Set<() => void>();

function setState(next: OnboardingState) {
  state = next;
  listeners.forEach((listener) => listener());
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

// Never run during the web server render: there is no storage there.
function load() {
  if (loadStarted) return;
  loadStarted = true;
  AsyncStorage.getItem(SEEN_KEY).then(
    (value) => setState(value === SEEN_VALUE ? 'seen' : 'unseen'),
    () => setState('unseen'), // unreadable storage: showing the slides again is harmless
  );
}

// In the browser and on native, start reading right away (in parallel with the session restore)
// instead of waiting for the first render. Skipped during the web server render.
if (typeof window !== 'undefined') load();

export function useOnboardingState(): OnboardingState {
  useEffect(load, []);
  return useSyncExternalStore(subscribe, () => state, () => state);
}

export function markOnboardingSeen() {
  setState('seen');
  AsyncStorage.setItem(SEEN_KEY, SEEN_VALUE).catch(() => undefined);
}

/** Debug: show the slides again (the sign-in screen's developer button). */
export function resetOnboarding() {
  setState('unseen');
  AsyncStorage.removeItem(SEEN_KEY).catch(() => undefined);
}
