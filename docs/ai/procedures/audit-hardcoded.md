# Procedure: audit hard-coded values and duplication

Input: a folder, file or "changed files" (default: files changed vs the main branch). Report first; only fix when asked.

Search for:
- Colors and spacing: hex colors, `rgb(`, inline `style={{`.
- URLs and hosts: `http://`, `https://`, `ws://`, `localhost`, ports.
- Timing and limits: `setTimeout`, `setInterval`, `sleep(`, `timeout=`, numeric literals such as 5, 10, 15, 30, 45, 60, 600, 1000, page sizes.
- Domain literals: role names, statuses, event types, error codes, slot counts (8), tolerance options.
- Text: JSX text and string props shown to users outside `Mobile/src/constants/strings.ts`, Python f-strings used as user messages.
- Secrets: keys, tokens, passwords, connection strings.
- Duplication: near-identical components, widgets or functions.

Output a table: `file:line | what | why it matters | proposed home (env, constants, theme token, i18n key, shared component)`.
Group by severity: secrets first, then user-facing strings, then magic numbers, then duplication. Skip allowed literals (0, 1, indexes, test fixtures).
