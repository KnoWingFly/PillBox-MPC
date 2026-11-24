# PillCare Mobile: caregiver app and auth server

Expo SDK 58 app for caregivers of the Smart Pillbox, plus the auth server (Expo Router API routes under
`src/app/api/`). The elderly person never uses this app. Contributor guide: `CLAUDE.md` in this folder.
Backend work the app already expects: `BACKEND_HANDOFF.md`. Project status: `../docs/PROJECT_STATUS.md`.

## Get started (local)

1. Install dependencies with **pnpm** (the lockfile is `pnpm-lock.yaml`):

   ```bash
   pnpm install
   pnpm exec prisma generate
   ```

2. Copy `.env.example` to `.env` and fill in the values. `JWT_ACCESS_SECRET` must be identical to the
   Backend's. Never put a server secret in an `EXPO_PUBLIC_*` variable.

3. Start the app and the auth server together:

   ```bash
   pnpm start        # expo start; press w for web, a for Android
   ```

   The auth API is served by the same dev server at `http://localhost:8081/api`.

4. To use real pillboxes instead of mock data, set `EXPO_PUBLIC_PILLBOX_API_URL` to the Backend
   (for example `http://localhost:8000`, or the laptop's LAN IP on a phone) and restart with
   `pnpm exec expo start -c`. When it is empty, the dashboard runs on in-memory mock data (`lib/api.ts`).

Useful checks: `pnpm exec tsc --noEmit` (typecheck) and `pnpm exec expo lint src lib components context`.
There is no test runner yet.

Database migrations: on the shared database use only `pnpm exec prisma migrate deploy`. Never run
`prisma migrate dev`, `migrate reset` or `db push` there (see `../docs/ai/architecture.md`, conflict 1).

## Where it runs

| Target | How |
|---|---|
| Web, local | `pnpm start`, then `w` |
| Web, hosted | Vercel, see "Deploy the web app and auth API to Vercel" below |
| Android/iOS | A development build (`expo run:android`) or an EAS build (`eas.json`: `development`, `preview` builds an APK, `production`). Expo Go cannot run native Google sign-in |

## Google sign-in

The website uses Supabase's Google OAuth redirect. Configure the Google provider in the Supabase
Dashboard with a Google **Web application** OAuth client ID and secret. In Google Cloud, add the
website origins (for example, `https://mpc-mobile.vercel.app` and, for local development,
`http://localhost:8081`) as authorized JavaScript origins. Add the **Supabase callback URL** shown
on the Supabase Google provider page as Google's authorized redirect URI; this is not the app
callback URL.

In Supabase **Authentication → URL Configuration**, set the **Site URL** to
`https://mpc-mobile.vercel.app` and add these app callback URLs to the redirect allowlist:

- `https://mpc-mobile.vercel.app/auth/google-callback`
- `http://localhost:8081/auth/google-callback` (local development)

The web app sends the current website origin as Supabase's `redirectTo`. If that URL is not allowed,
Supabase falls back to the Site URL, which can send users to an old `localhost` address if the Site
URL is still configured for local development.

Set `EXPO_PUBLIC_SUPABASE_URL`, `EXPO_PUBLIC_SUPABASE_KEY`, and `SUPABASE_SECRET_KEY` in the local
environment; the last value is server-only. The auth API also needs its normal database and
`JWT_ACCESS_SECRET` settings. Restart Expo after changing environment values. Then run `pnpm web`
and use **Lanjutkan dengan Google** on the Masuk screen.

On a phone, Google sign-in uses the native Google Sign-In module and does not work in Expo Go.
Install the SDK-compatible development client with `pnpm exec expo install expo-dev-client`, then
build and run it with `pnpm exec expo run:android` (Android Studio/device required). Configure a
Google Android OAuth client with the app's Android package name and the SHA-1 of the certificate
that signs the development build; add that client ID to Supabase's Google provider. Set
`EXPO_PUBLIC_GOOGLE_WEB_CLIENT_ID` to the Google Web client ID and
`EXPO_PUBLIC_SUPABASE_URL`, `EXPO_PUBLIC_SUPABASE_KEY`, and server-side `SUPABASE_SECRET_KEY` in
the environment before building.

For iOS, configure a Google iOS OAuth client for the app's bundle ID, add it to Supabase, and set
`EXPO_PUBLIC_GOOGLE_IOS_CLIENT_ID`. Replace the `iosUrlScheme` placeholder in `app.json` with the
reversed iOS client ID (`com.googleusercontent.apps.<client-id-prefix>`) before generating the
development build. An iOS build requires macOS/Xcode or an EAS Build environment.

### Deploy the web app and auth API to Vercel

Create a Vercel project for this repository and set **Root Directory** to `Mobile`. The
`vercel.json` here builds the Expo web server and routes requests through Expo Router API routes.
The build command also generates Prisma's Vercel Linux query engine and includes it in the server
function bundle; Vercel serves static assets from `dist/client`.

Add these values in **Vercel → Project Settings → Environment Variables**. Use different URLs and
credentials for Preview and Production as appropriate:

- Required server variables: `DATABASE_URL` (Supabase transaction pooler), `DIRECT_URL` (database
  direct/session connection), `JWT_ACCESS_SECRET` (at least 32 characters and identical to the
  Backend's value), `EXPO_PUBLIC_SUPABASE_URL`, `EXPO_PUBLIC_SUPABASE_KEY`, and
  `SUPABASE_SECRET_KEY`.
- Required client build variables: `EXPO_PUBLIC_SUPABASE_URL` and `EXPO_PUBLIC_SUPABASE_KEY`.
  These are public Supabase values; all `EXPO_PUBLIC_*` variables are included in the web bundle.
- Set `EXPO_PUBLIC_PILLBOX_API_URL` to the deployed Backend HTTPS base URL to use real devices
  instead of mock dashboard data.
- For native app builds that call the auth API, set `EXPO_PUBLIC_API_URL` to this Vercel deployment
  URL. Leave it empty for the web app, which calls the API on the same origin.
- For native Google sign-in, set `EXPO_PUBLIC_GOOGLE_WEB_CLIENT_ID`. For hosted web sign-in,
  add `https://<your-vercel-domain>/auth/google-callback` to Supabase's allowed redirect URLs and
  the Vercel origin to Google Cloud's authorized JavaScript origins. The Google client secret
  belongs in Supabase, not in Vercel or an `EXPO_PUBLIC_*` variable.
- To send password-reset emails, set `RESEND_API_KEY` and `EMAIL_FROM`. `OTP_PEPPER` is optional;
  if set, keep it server-only and stable.

Never put `JWT_ACCESS_SECRET`, `SUPABASE_SECRET_KEY`, database URLs, Resend keys, or OTP peppers
in an `EXPO_PUBLIC_*` variable. Copy the variable names and connection-string format from
`.env.example`, but enter real values directly in Vercel rather than committing them. Redeploy after
changing client build variables.

### Native builds with EAS

`eas.json` defines three profiles: `development` (development client, internal), `preview` (internal,
Android APK) and `production` (store build, version auto-incremented). The EAS project ID is in
`app.json` (`extra.eas.projectId`); it also lets `expo-notifications` obtain an Expo push token.
Set the `EXPO_PUBLIC_*` values for the build in EAS environment variables. iOS still needs the real
`iosUrlScheme` in `app.json` (see "Google sign-in" above).

## Expo references

The app follows Expo SDK 58. Check the versioned docs before changing an Expo API:
https://docs.expo.dev/versions/v58.0.0/
