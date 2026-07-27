# Changelog

All notable changes to this project are documented in this file.

## [0.2.0] - 2026-07-27

### Added

- A Python 3.12 slim Docker image for the FastAPI service.
- A Docker Compose configuration with a configurable loopback-bound host port.
- Container health checks and non-root runtime execution.
- Automated Docker configuration tests and a GitHub Actions container smoke test.
- Docker deployment instructions in both the Chinese and English README files.

### Security

- Local `.env` files, development artifacts, tests, and private data are excluded from the
  Docker build context.
- The API container runs as an unprivileged system user.
- The default Compose port binding is limited to `127.0.0.1`.

### Validation

- 524 automated tests pass.
- Ruff linting and formatting checks pass.
- Mypy static type checking passes.
- The Docker container builds, becomes healthy, and passes the CI smoke test.

## [0.1.0] - 2026-07-24

- Initial interview-ready release of the offline-safe AI sales lead cleaning, scoring, RAG,
  FastAPI, CLI, and n8n demonstration pipeline.

[0.2.0]: https://github.com/jorlin1101-cyber/ai-sales-lead-crm-automation/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/jorlin1101-cyber/ai-sales-lead-crm-automation/releases/tag/v0.1.0
