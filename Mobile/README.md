# Welcome to your Expo app 👋

This is an [Expo](https://expo.dev) project created with [`create-expo-app`](https://www.npmjs.com/package/create-expo-app).

## Get started

1. Install dependencies

   ```bash
   npm install
   ```

2. Start the app

   ```bash
   npx expo start
   ```

In the output, you'll find options to open the app in a

- [development build](https://docs.expo.dev/develop/development-builds/introduction/)
- [Android emulator](https://docs.expo.dev/workflow/android-studio-emulator/)
- [iOS simulator](https://docs.expo.dev/workflow/ios-simulator/)
- [Expo Go](https://expo.dev/go), a limited sandbox for trying out app development with Expo

You can start developing by editing the files inside the **app** directory. This project uses [file-based routing](https://docs.expo.dev/router/introduction).

## Get a fresh project

When you're ready, run:

```bash
npm run reset-project
```

This command will move the starter code to the **app-example** directory and create a blank **app** directory where you can start developing.

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

### Other setup steps

- To set up ESLint for linting, run `npx expo lint`, or follow our guide on ["Using ESLint and Prettier"](https://docs.expo.dev/guides/using-eslint/)
- If you'd like to set up unit testing, follow our guide on ["Unit Testing with Jest"](https://docs.expo.dev/develop/unit-testing/)
- Learn more about the TypeScript setup in this template in our guide on ["Using TypeScript"](https://docs.expo.dev/guides/typescript/)

## Learn more

To learn more about developing your project with Expo, look at the following resources:

- [Expo documentation](https://docs.expo.dev/): Learn fundamentals, or go into advanced topics with our [guides](https://docs.expo.dev/guides).
- [Learn Expo tutorial](https://docs.expo.dev/tutorial/introduction/): Follow a step-by-step tutorial where you'll create a project that runs on Android, iOS, and the web.

## Join the community

Join our community of developers creating universal apps.

- [Expo on GitHub](https://github.com/expo/expo): View our open source platform and contribute.
- [Discord community](https://chat.expo.dev): Chat with Expo users and ask questions.
