---
paths:
  - "Mobile/src/**/*.tsx"
  - "Mobile/components/**/*.tsx"
  - "Mobile/context/**/*.tsx"
---

# Mobile UI

- Screens in `src/app/` are thin: compose components and hooks/context, no business logic.
- Search `src/components/pillbox/ui.tsx` and `src/components/` before writing markup; anything used twice becomes a shared component with typed props.
- Styling uses NativeWind classes backed by `src/theme/tokens.js`. No new hex colors or inline style objects. Light mode only for now.
- User-facing text is Indonesian and goes in `src/constants/strings.ts` (no i18n library yet). API error codes map to messages in `src/lib/api/error-message.ts`.
- Timings, intervals, limits and URLs come from `AppConfig` in `src/config.ts`.
- Lists use FlatList with `keyExtractor` and memoized rows; no inline lambdas in rows.
- Show dose times in the device timezone.
- Never import Prisma or `src/server/` modules here.
