# AI agent setup for PillCare (Claude Code + Antigravity)

Shared by all four members. Commit everything here; keep personal overrides local.

## What is where
```
CLAUDE.md                         core rules for the whole repo (tool-neutral text)
AGENTS.md                         Antigravity root rules: includes CLAUDE.md
Mobile|Backend|SmartDevice/
  CLAUDE.md                       folder guide (single source)
  AGENTS.md                       Antigravity wrapper: includes the sibling CLAUDE.md
docs/ai/
  domain.md, architecture.md      shared facts, ownership, known conflicts + fixes
  procedures/*.md                 steps for the 5 reusable procedures (single source)
.claude/
  settings.json                   permissions (deny .env reads, deny destructive Prisma commands; ask before adding packages, migrating or pushing)
  rules/*.md                      path-scoped rules (load when matching files are touched)
  agents/*.md                     subagents: contract-reviewer, migration-guard, quality-reviewer
  commands/*.md                   slash commands that point to docs/ai/procedures
.agents/
  rules/*.md                      Antigravity rules (model_decision / glob); bodies come from .claude/rules
  skills/*/SKILL.md               Antigravity skills that point to docs/ai/procedures
CLAUDE.local.md.example           copy to CLAUDE.local.md for personal notes
```
Edit text in one place only: `CLAUDE.md` files, `.claude/rules/*`, and `docs/ai/*`. The Antigravity files point at them.

## Install
Already installed in this repo (`.gitignore` covers `CLAUDE.local.md`, `.claude/settings.local.json` and `.env*` except examples). Open the repo in Claude Code or Antigravity and start a new session.

`Mobile/.claude/`, `Mobile/.agents/`, `Mobile/.cursor/` and `Mobile/.devin/` hold Prisma skills synced by `pnpm install` (`prisma skills sync`); `Mobile/.claude/settings.json` enables the Expo plugin. Leave them alone.

## Verified on 23 Oct 2026 (from current docs)
- Antigravity: rules are `AGENTS.md` / `GEMINI.md` (no frontmatter, always on) plus `.agents/rules/*.md` (flat folder, frontmatter with `trigger` = `always_on | model_decision | glob | manual` is required; `globs` for glob, `description` for model_decision). Nested `AGENTS.md` apply when working in that directory. `@[label](path)` inlines a file.
- Antigravity workflows stopped working on 19 Oct 2026; reusable procedures are skills in `.agents/skills/<name>/SKILL.md` (frontmatter `name`, `description`).
- Claude Code: nested `CLAUDE.md` load on demand; `.claude/rules/*.md` with `paths:` globs; `.claude/agents/*.md` frontmatter (`name`, `description`, `tools`, `model`); `.claude/commands/*.md` still work (skills are recommended for new work); `settings.json` permissions order is deny, ask, allow. `CLAUDE.local.md` is not gitignored automatically.

## Checked against the code on 23 Oct 2026
Folder layouts, commands, env names, migration numbering, error body shape, JWT sharing, Google verification path and event types in the guides match the code as of that date. If you restructure a folder, update its `CLAUDE.md` and the `paths:` globs in `.claude/rules/` in the same PR.

Permission and rule syntax confirmed from the official docs on 23 Oct 2026: a `Bash(cmd *)` rule also matches the bare `cmd`; deny/ask rules apply to each part of a compound command (`cd X && cmd`) but not to rewritten forms such as `pnpm -C Mobile exec ...`; `Read(**/.env)` matches at any depth; `.claude/rules` `paths:` globs are relative to the repo root; Antigravity `globs` accepts comma-separated patterns and only reads files directly inside `.agents/rules/`.

## Not verified (check before relying on it)
- Expo API route hosting outside the dev server.
- Whether the API list spreadsheet has fields or codes the code does not implement yet.
- Antigravity subagents were not configured; only rules and skills were.

## Open decisions (see `architecture.md`)
Auth server hosting, account deletion for OWNERs, `notify_on_taken` default, device secret label in the mockups. (JWT sharing, Google verification and error body shape are decided.)

## Contract and schema links
- API list: https://docs.google.com/spreadsheets/d/1VNqQSYk_syjNwLWFM7MFgtgstKPlbYqLhLAHlUGMuKk/edit?usp=sharing (copied from a PDF line break, open it to confirm)
- ERD: https://dbdiagram.io/d/Pillbox-ERD-v2-6ab495070f25a52d01f0612b
