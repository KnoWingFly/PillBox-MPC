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
website origin (for local development, `http://localhost:8081`) as an authorized JavaScript origin,
and add the Supabase callback URL shown on the Supabase Google provider page as an authorized
redirect URI. In Supabase URL Configuration, allow the app callback URL
`http://localhost:8081/auth/google-callback`.

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
