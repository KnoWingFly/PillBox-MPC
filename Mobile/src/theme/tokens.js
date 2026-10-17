// Design tokens: the single source for colors, spacing, radius, type and shadows.
// CommonJS so tailwind.config.js can require it; TS code imports it for props that do not take
// classes (Switch trackColor, ActivityIndicator color, RefreshControl).
//
// Light mode only for now. Names are semantic (ink, canvas, status.*), so dark mode can later map
// the same names to other values (e.g. NativeWind vars()) without touching components.
//
// Contrast (WCAG AA, 4.5:1 for text) was checked for every text/background pair used:
//   white on primary 5.47, white on primary.pressed 7.58, primary on primary.light 5.25,
//   ink.muted on canvas 6.92, status fg on status soft 6.27-7.60, white on status solid 5.02-6.47.
//   ink.subtle (#64748B) is 4.76 on white but only 4.34 on canvas: use it on white surfaces only.

const colors = {
  primary: {
    DEFAULT: '#0F766E', // teal-700
    pressed: '#115E59',
    light: '#F0FDFA', // soft background (selected slot, editor)
    dark: '#134E4A', // text on primary.light
  },
  canvas: '#F1F5F9', // page background
  surface: { DEFAULT: '#FFFFFF', muted: '#F8FAFC' }, // cards; read notifications
  ink: { DEFAULT: '#0F172A', muted: '#475569', subtle: '#64748B' },
  line: { DEFAULT: '#E2E8F0', strong: '#64748B' }, // decorative dividers; control borders (>= 3:1)
  // Status colors. fg = text/icon on soft; solid = filled buttons/accents with white text.
  ontime: { fg: '#166534', soft: '#F0FDF4', solid: '#15803D', border: '#BBF7D0' }, // Tepat waktu (green)
  late: { fg: '#92400E', soft: '#FFFBEB', solid: '#B45309', border: '#FDE68A' }, // Terlambat (amber)
  missed: { fg: '#991B1B', soft: '#FEF2F2', solid: '#B91C1C', border: '#FECACA' }, // Terlewat / danger (red)
  battery: { fg: '#455A64', soft: '#ECEFF1' }, // blue-grey
  info: { fg: '#075985', soft: '#F0F9FF', solid: '#0369A1' }, // Sistem
};

/** Allowed spacing steps (px). Tailwind's default scale already matches: 1=4, 2=8, 3=12, 4=16, 6=24, 8=32. */
const spacing = { xs: 4, sm: 8, md: 12, lg: 16, xl: 24, xxl: 32 };

/** Corner radius (px). Tailwind equivalents: lg=8, xl=12, 2xl=16, 3xl=24. */
const radius = { sm: 8, md: 12, lg: 16, xl: 24, full: 9999 };

/** [fontSize, lineHeight] in px. Large by default: many caregivers are older adults. */
const fontSize = {
  caption: [14, 20], // timestamps and hints only
  'body-sm': [16, 24],
  body: [18, 26],
  title: [20, 28],
  heading: [24, 32],
  display: [30, 36],
  time: [36, 44],
};

const shadow = {
  card: '0px 1px 3px rgba(15, 23, 42, 0.08)',
  raised: '0px 6px 16px rgba(15, 23, 42, 0.16)',
};

module.exports = { colors, spacing, radius, fontSize, shadow };
