# JDK ERP

A clean-slate rebuild of the JDK ERP system.

This repository starts from a blank project. The previous implementation
(`jdk_clean`) is kept only as a reference for business workflows — no code
is carried over. Every module here is built against the rules in
[`docs/ENGINEERING_PRINCIPLES.md`](docs/ENGINEERING_PRINCIPLES.md), which is
the project-wide contract for how this codebase is designed, reviewed and
extended.

## Start here

- [`docs/ENGINEERING_PRINCIPLES.md`](docs/ENGINEERING_PRINCIPLES.md) —
  read this before writing any code. It governs architecture, security,
  data integrity, UI consistency and review standards for the whole
  project.
- [`docs/ROADMAP.md`](docs/ROADMAP.md) — the phase-by-phase build order,
  from foundation through hardening, and the dependency graph between
  modules.
- [`docs/DESIGN_SYSTEM.md`](docs/DESIGN_SYSTEM.md) — colour palette,
  typography and status-colour conventions for the standard UI system.
- [`CONTRIBUTING.md`](CONTRIBUTING.md) — how to propose and land a change.

## Project layout

```
backend/    Server-side application: API, business logic, database access.
frontend/   Web client.
docs/       Engineering principles and other project-wide documentation.
```

Structure will grow as modules are added — see each directory's own README
for its current state.

## Status

Early scaffolding. No business functionality has been implemented yet.
