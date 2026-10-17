// Types for tokens.js (kept as CommonJS so tailwind.config.js can require it).

type StatusTone = { fg: string; soft: string; solid: string; border: string };

export declare const colors: {
  primary: { DEFAULT: string; pressed: string; light: string; dark: string };
  canvas: string;
  surface: { DEFAULT: string; muted: string };
  ink: { DEFAULT: string; muted: string; subtle: string };
  line: { DEFAULT: string; strong: string };
  ontime: StatusTone;
  late: StatusTone;
  missed: StatusTone;
  battery: { fg: string; soft: string };
  info: { fg: string; soft: string; solid: string };
};
export declare const spacing: { xs: 4; sm: 8; md: 12; lg: 16; xl: 24; xxl: 32 };
export declare const radius: { sm: 8; md: 12; lg: 16; xl: 24; full: 9999 };
export declare const fontSize: Record<'caption' | 'body-sm' | 'body' | 'title' | 'heading' | 'display' | 'time', [number, number]>;
export declare const shadow: { card: string; raised: string };
