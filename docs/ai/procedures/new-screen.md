# Procedure: build a Mobile screen

Input: the screen name from the mockups (Onboarding, Sign in / Sign up, Dashboard, Pillbox main, Connect pillbox, Schedule Control, History, Change PIN, Notifications, Settings, Add elderly profile). First check whether it already exists as a tab in `src/components/pillbox/` or a route in `src/app/`.

1. List the data the screen needs and map each item to an API list endpoint. Missing endpoint = stop and report; do not mock silently.
2. Search `src/components/pillbox/ui.tsx` and `src/components/` for reusable pieces. Reuse first; extract a shared component when the same markup would appear twice.
3. Data: add typed calls in `lib/` (Backend) or `src/lib/api/` (auth server) and expose them through a hook in `src/hooks/` or the existing context (`context/`). Poll with intervals from `AppConfig`.
4. Build the route in `src/app/` as a thin composition of components. Cover loading, empty, error and offline states (`LoadErrorBox`, `EmptyState`).
5. Styling: NativeWind classes from `src/theme/tokens.js` only. No hex values, no inline style objects.
6. Text: Indonesian copy in `src/constants/strings.ts`. Map API error codes in `src/lib/api/error-message.ts`.
7. Lists use FlatList with `keyExtractor` and memoized rows. Dose times display in the device timezone.
8. Accessibility: contrast, 44 pt tap targets, labels for icon buttons.
9. Run `pnpm exec tsc --noEmit` and `pnpm exec expo lint src lib components context` in `Mobile/` (2 existing lint errors are known, see `Mobile/CLAUDE.md`) and report the result honestly. Mention what you could not run.
