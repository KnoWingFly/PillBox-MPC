const tokens = require("./src/theme/tokens");

/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./src/app/**/*.{js,jsx,ts,tsx}", "./src/components/**/*.{js,jsx,ts,tsx}", "./components/**/*.{js,jsx,ts,tsx}"],
  presets: [require("nativewind/preset")],
  darkMode: "class",
  theme: {
    extend: {
      // All app colors come from src/theme/tokens.js (e.g. bg-primary, text-ink-muted, bg-late-soft).
      colors: tokens.colors,
      fontSize: Object.fromEntries(
        Object.entries(tokens.fontSize).map(([name, [size, lineHeight]]) => [name, [`${size}px`, `${lineHeight}px`]]),
      ),
    },
  },
  plugins: [],
};
