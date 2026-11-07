# Changelog

Notable changes to Vektor Desk. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and versions follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html): each roadmap phase is a minor version, and fixes between phases are patches. Planned work is in [ROADMAP.md](ROADMAP.md).

## Unreleased

### Added

- Infrastructure: compose stack for TrueNAS (Tailscale sidecar, Caddy with Porkbun DNS-01), read-only Firestore mirror with change history, scheduler, backups, deploy and setup scripts ([#5])
- Package seams: routers from `desk/*/api.py`, schemas from `desk/*/schema.py` applied to `desk.db` at startup, jobs from `desk/*/jobs.py` under run locks, and shared test fixtures ([#9])
- Synthetic demo data: `desk/demo.py` builds a two-year synthetic `mirror.db` for tests (`demo_cfg`) and demo mode (`DESK_DEMO=1`) ([#14])

## 0.0.0 - 2026-11-07

Planning: concept, architecture, statistics, agents and design plans, roadmap and project plan ([#1], [#2], [#3], [#4], [#6]).

[#1]: https://github.com/inzodious/vektor-desk/pull/1
[#2]: https://github.com/inzodious/vektor-desk/pull/2
[#3]: https://github.com/inzodious/vektor-desk/pull/3
[#4]: https://github.com/inzodious/vektor-desk/pull/4
[#5]: https://github.com/inzodious/vektor-desk/pull/5
[#6]: https://github.com/inzodious/vektor-desk/pull/6
[#9]: https://github.com/inzodious/vektor-desk/pull/9
[#14]: https://github.com/inzodious/vektor-desk/pull/14
