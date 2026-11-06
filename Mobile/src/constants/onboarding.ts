// Sample data drawn in the onboarding illustrations. Not live data and never sent anywhere.

export type DemoSlotState = 'taken' | 'active' | 'upcoming';

/** The 8-slot tray preview on the first slide: number shown on the slot, dose time, state. */
export const DEMO_SLOTS: readonly { label: string; time: string; state: DemoSlotState }[] = [
  { label: '01', time: '06:00', state: 'taken' },
  { label: '02', time: '07:00', state: 'taken' },
  { label: '03', time: '07:30', state: 'taken' },
  { label: '04', time: '08:00', state: 'active' },
  { label: '05', time: '12:30', state: 'upcoming' },
  { label: '06', time: '15:00', state: 'upcoming' },
  { label: '07', time: '18:30', state: 'upcoming' },
  { label: '08', time: '21:00', state: 'upcoming' },
];

/** Share of today's doses taken in the preview (3 of 8). */
export const DEMO_COMPLIANCE_RATIO = 3 / 8;

/** Gentle pulse on the active slot (ms per half cycle, peak scale). */
export const ACTIVE_SLOT_PULSE_MS = 900;
export const ACTIVE_SLOT_PULSE_SCALE = 1.06;

/** The panel beside Masuk / Buat Akun on wide screens shows the next onboarding slide this often (ms). */
export const AUTH_ASIDE_ROTATE_MS = 5_000;
/** Slide animation between those slides (ms). */
export const AUTH_ASIDE_SLIDE_MS = 500;
