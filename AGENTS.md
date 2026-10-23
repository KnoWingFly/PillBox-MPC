# PillCare — Antigravity rules

@[Project guide](CLAUDE.md)

## Antigravity specifics
- Folder guides load automatically from the nested `AGENTS.md` files (`Mobile/`, `Backend/`, `SmartDevice/`); each one includes the sibling `CLAUDE.md`, so there is a single source of truth.
- Detailed rules live in `.agents/rules/` (activated by description or file glob). Procedures are skills in `.agents/skills/`.
- For work that touches more than one file, produce an implementation plan first, then a walkthrough when done.
- Shared references (read them when a task touches roles, doses, the device protocol, tables or auth):
  - @docs/ai/domain.md
  - @docs/ai/architecture.md
  - @docs/DEVICE_CONTRACT.md
