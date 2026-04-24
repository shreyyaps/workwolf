# Wolfie Docs

Two documents, both grounded in the current code (not the top-level
`README.md`, which is still a scratchpad).

- [`semantic.md`](./semantic.md) — what the project is, the mental model,
  the actors, the HTTP surface, startup flow, and what lives on disk.
  Start here if you have never seen this repo before.
- [`design-decisions.md`](./design-decisions.md) — the "why" behind the
  current shape: separate daemon, loopback-only, raw subprocess Chrome,
  profile persistence, etc. Read this before changing architecture.

If something in these docs disagrees with the code, trust the code and
fix the doc.
