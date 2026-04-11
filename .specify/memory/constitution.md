# Django Jobs Constitution

## Core Principles

### I. Architecture & Code Quality
- **Clean Architecture**: MUST maintain clear separation between Domain, Application (Use Cases), and Infrastructure layers.
- **Ruff Enforcement**: MUST use `ruff` for linting and formatting; all code MUST pass `ruff check` and `ruff format` without errors.
- **Type Safety**: MUST use type hints for all public function signatures and class attributes.
- **DRY & SOLID**: MUST adhere to DRY principles and SOLID design patterns to ensure maintainability.
- **Explicit Error Handling**: MUST handle exceptions explicitly and log them with context; never fail silently.

### II. Testing Standards
- **Coverage**: Aim for 80%+ code coverage for business logic and core infrastructure.
- **TDD Preferred**: Write tests alongside implementation.
- **Unit & Integration**: MUST include unit tests for domain logic and integration tests views/API endpoints.
- **Isolation**: MUST mock external dependencies (external APIs, file system) in unit tests.
- **pytest**: MUST use `pytest` as the test runner.

### III. Technology Stack
- **Framework**: FastAPI (latest stable).
- **Database**: PostgreSQL.
- **Containerization**: Docker & Docker Compose for development and deployment.
- **Package Management**: `poetry` for dependency management.

## Development Workflow
1. **Spec-Kit**: MUST follow the `Spec -> Plan -> Tasks` workflow for any non-trivial change.
2. **Quality Gates**: `ruff check`, `ruff format`, and `pytest` MUST pass before implementation is considered complete.

**Version**: 1.1.0 | **Ratified**: 2026-03-27 | **Last Amended**: 2026-03-27
