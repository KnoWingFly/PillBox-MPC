const tokens = require("./src/theme/tokens");

/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./src/app/**/*.{js,jsx,ts,tsx}", "./src/components/**/*.{js,jsx,ts,tsx}", "./components/**/*.{js,jsx,ts,tsx}"],
  presets: [require("nativewind/preset")],
  darkMode: "class",
  theme: {
    extend: {
      // Breakpoints from tokens.js (also read by src/hooks/use-breakpoint.ts).
      screens: Object.fromEntries(Object.entries(tokens.breakpoints).map(([name, px]) => [name, `${px}px`])),
      // All app colors come from src/theme/tokens.js (e.g. bg-primary, text-ink-muted, bg-late-soft).
      colors: tokens.colors,
      fontSize: Object.fromEntries(
        Object.entries(tokens.fontSize).map(([name, [size, lineHeight]]) => [name, [`${size}px`, `${lineHeight}px`]]),
      ),
    },
  },
  plugins: [],
};
