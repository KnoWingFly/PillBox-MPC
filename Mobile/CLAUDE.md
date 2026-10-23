# Mobile — PillCare caregiver app + auth server

Expo SDK 57, React Native 0.86, React 19, TypeScript (strict), Expo Router (typed routes, React Compiler on), NativeWind 4 + Tailwind 3, pnpm, Prisma 6 (server code only), Supabase Auth (Google SSO only), zod. Caregiver-only: elderly never use this app. app.json scheme: `pillcareapp`.
Read `docs/ai/domain.md` before changing anything about roles, doses, schedules or notifications. Open backend work that the app already expects: `Mobile/BACKEND_HANDOFF.md`.

## Expo changes every SDK: do not trust memory
Before touching an Expo or React Native API, read the version in `package.json` and check the versioned docs (`https://docs.expo.dev/versions/v57.0.0/`, index at `https://docs.expo.dev/llms.txt`). Add packages with `pnpm exec expo install <pkg>` (picks SDK-compatible versions), never plain `pnpm add`. `ios/` and `android/` are generated (CNG): configure native behavior in `app.json` and config plugins only. Libraries with native code need a development build, not Expo Go (Google sign-in already does).

## Two runtimes in one folder
1. **App (React Native)**: screens, components, hooks. No secrets, no Prisma, no direct Supabase table access (RLS is on with no policies).
2. **Auth server (Expo Router API routes, `app.json` web output `server`)**: implements API list section A at `<EXPO_PUBLIC_API_URL or the dev server>/api`: `/auth/*`, `/setting`, `/setting/push-tokens`. Route files are `src/app/api/**/*+api.ts`; their logic lives in `src/server/` (Prisma client, tokens, passwords, OTP, email, errors). Server-only env: `DATABASE_URL`, `DIRECT_URL`, `JWT_ACCESS_SECRET` (must equal the Backend's), `SUPABASE_SECRET_KEY`, `RESEND_API_KEY`, `EMAIL_FROM`, `OTP_PEPPER`. Never prefix these with `EXPO_PUBLIC_`.

Everything else (sections B-G) is served by `Backend/` at `EXPO_PUBLIC_PILLBOX_API_URL` + `/api/v1`. When that variable is unset the dashboard runs on in-memory mock data (`lib/api.ts`). See `docs/ai/architecture.md` for data ownership.

## Commands (package.json scripts)
- `pnpm install`, `pnpm start` (`expo start`)
- Lint: `pnpm exec expo lint src lib components context`. Plain `pnpm lint` fails ("No files matching the pattern .../Mobile/app") because routes live in `src/app/`. As of 23 Oct 2026 lint reports 2 existing errors (`src/hooks/use-color-scheme.web.ts` setState in effect, `src/server/env.ts` dynamic `process.env` access); judge your change by any new errors only.
- Typecheck: `pnpm exec tsc --noEmit`
- Prisma: `pnpm exec prisma generate`, `pnpm exec prisma validate`, and on the shared database only `pnpm exec prisma migrate deploy`. Never `prisma migrate dev`, `migrate reset` or `db push` against the shared database: Prisma sees the Backend tables as drift and offers to reset it (see `docs/ai/architecture.md`, conflict 1).
- Auth smoke script: `scripts/auth-smoke.ts` (run with `pnpm exec tsx`).
- There is no test runner yet (no Jest). Do not claim tests pass.

## Layout (match it; do not mass-move)
```
src/app/                  Expo Router routes: _layout.tsx, index.tsx (pillbox dashboard), auth/*, explore.tsx
src/app/api/              auth server routes (section A), *+api.ts
src/server/               server-only code for the API routes (never imported by app code)
src/components/pillbox/   dashboard tabs and feature components; ui.tsx holds the shared primitives
                          (Button, Chip, Card, ScreenHeader, StatusPill, InfoRow, EmptyState, LoadErrorBox, IconBadge, Icon)
src/components/ui/        generic pieces (collapsible)
src/hooks/                use-auth, use-notification-feed, use-theme, use-color-scheme
src/lib/api/              API client (apiFetch, token refresh, timeouts), auth + setting calls, token-store, error messages
src/config.ts             AppConfig: every env-driven value (URLs, timeouts, poll intervals, page sizes)
src/constants/strings.ts  UI copy (Indonesian)
src/theme/tokens.js       design tokens (colors, font sizes) consumed by tailwind.config.js
lib/                      pillbox data layer for the Backend (api.ts, devices.ts, feed.ts, notifications.ts, types.ts, ...)
components/auth/, context/  auth form pieces, auth-context and devices-context providers
prisma/schema.prisma      account tables only; migrations in prisma/migrations/
```
Imports: `@/` = `src/`, `@root/` = the Mobile folder root.

## Rules
- **Screens are thin.** Logic goes to hooks/context, visuals to components. Before writing markup, search `src/components/pillbox/ui.tsx` and `src/components/`; anything used twice becomes a shared component with typed props.
- **Styling**: NativeWind classes backed by `src/theme/tokens.js` (e.g. `bg-primary`, `text-ink-muted`). Props that cannot take classes read `tokens` directly. No new hex colors or inline style objects in components. The tokens are light-only (`app.json` says `automatic`, but no dark styling is built); do not add dark styling without the team.
- **No hard-coded values**: env-driven values go in `AppConfig` (`src/config.ts`) and `.env.example`; tunable constants in a constants module. Realtime: `lib/api.ts` already holds the one `/ws/app` client (`subscribeToDeviceChanges`, `isRealtimeLive`, `resubscribeRealtime`); pushes carry the changed rows/status and are applied directly (refetch only when a message has no data). Polling is the fallback: `notificationPollMs` (5 s) and `deviceStatusPollMs` (10 s), slowed to `REALTIME_FALLBACK_POLL_MS` while the socket is live. Never open a second socket.
- **Text**: UI copy is Indonesian. Put new strings in `src/constants/strings.ts` (some older components still keep copy inline, e.g. `src/components/pillbox/helpers.ts`; move it when you touch it). There is no i18n library and no English locale yet; do not add one without the team.
- **API errors**: both servers answer `{"error": {"code", "message", "details"?}}`; map `code` to a message in `src/lib/api/error-message.ts`.
- **No hard-coded URLs**: read base URLs only from `AppConfig`.
- **Types mirror the API list exactly** (snake_case on the wire); map only at the UI boundary.
- **Server state**: existing hooks + context, `/ws/app` push + polling fallback. There is no TanStack Query; do not add it without asking.
- **Lists** use FlatList with `keyExtractor` and memoized rows.
- **Tokens**: `src/lib/api/token-store.ts` only (SecureStore on native, web storage on web). AsyncStorage is for non-secret values only (e.g. the selected device id). Never log tokens, PINs or OTPs.
- **Prisma** is imported only under `src/server/` and API routes.
- **Dates**: show dose times in the device timezone (`AppConfig.fallbackTimezone` when the device has none).
- **Accessibility**: readable contrast (see the contrast notes in `tokens.js`), tap targets of at least 44 pt.
