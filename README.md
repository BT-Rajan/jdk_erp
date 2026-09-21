# JDK ERP

A clean-slate rebuild of the JDK ERP system.

This repository starts from a blank project, built by auditing the
previous implementation (`jdk_clean`) module by module — see
[`docs/ROADMAP.md`](docs/ROADMAP.md) §Phase 0. Where a module already
holds up, it's ported forward and hardened rather than rewritten; where it
doesn't, it's rebuilt clean. Every module is built and reviewed against
[`docs/ENGINEERING_PRINCIPLES.md`](docs/ENGINEERING_PRINCIPLES.md), the
project-wide contract for how this codebase is designed.

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
- [`docs/audit/`](docs/audit/) — Phase 0 audit findings per module, each
  ending in a reuse-vs-rebuild verdict and an action-item list.
- [`docs/modules/`](docs/modules/) — the definition/spec for each module,
  written before implementation starts.
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
