# SoftDesk Support — Secure REST API (Django REST Framework)
![CI](https://github.com/SiRipo92/SoftDesk_Django_API/actions/workflows/ci.yml/badge.svg)
![Ruff](https://img.shields.io/badge/linted%20with-ruff-261230.svg)

School project: build a secure REST API with JWT auth, role-based permissions, OWASP-inspired protections, and test strategy (Postman + automated tests).

## Tech stack
- Python 3.12
- Django + Django REST Framework
- SQLite (local development database)
- SimpleJWT (access/refresh + blacklist)
- drf-spectacular (OpenAPI/Swagger schema generation for documentation + Postman import)
- Postman (API client: shared collection + environment)
- Poetry (dependency management)
- Ruff (lint + format)
- Pytest + pytest-django (+ pytest-cov for coverage)
- GitHub Actions (CI: lint + format check + tests + coverage artifacts)

## Table of Contents
- [Setup (local)](#setup-local)
- [Quality checks (lint/format)](#quality-checks-lintformat)
- [Tests (PyTest)](#tests-pytest)
- [Django Utility Commands](#django-utility-commands)
- [Collection + Environment (recommended)](#collection--environment-recommended)
- [OpenAPI (drf-spectacular)](#openapi-drf-spectacular)
- [Project Structure](#project-structure)
- [Security (OWASP-inspired protections)](#security-owasp-inspired-protections)
- [Green Code (performance/efficiency)](#green-code-performanceefficiency)
- [Quality checks (CI)](#quality-checks-ci)
  - [Lint (Ruff)](#lint-ruff)
  - [Format check (fails if formatting differs)](#format-check-fails-if-formatting-differs)
  - [Auto-format (applies formatting)](#auto-format-applies-formatting)
  - [Run tests](#run-tests)
  - [Run tests + coverage (terminal + HTML report)](#run-tests--coverage-terminal--html-report)
- [Coverage reports](#coverage-reports)


## Setup (local)
### 1) Install dependencies
```bash
poetry install
```

### 2) Apply database migrations
```bash
poetry run python manage.py migrate
```

### 3) Run the API (dev)
```bash
poetry run python manage.py runserver
```

## Quality checks (lint/format)
### 1) Run lint
```bash
poetry run ruff check .
```

### 2) Auto-fix lint issues (when possible)
```bash
poetry run ruff check . --fix
```

### 3) Format code
```bash
poetry run ruff format .
```

## Tests (PyTest)
### 1) Run all tests
```bash
poetry run pytest
```

### 2) Run tests with quieter output
```bash
poetry run pytest -q
```

### 3) Run tests with coverage
```bash
poetry run pytest --cov=apps --cov-report=term-missing
```

### 4) Generate an HTML coverage report
```bash
poetry run pytest --cov=apps --cov-report=html
```

## Django Utility Commands
### 1) Run system checks
```bash
poetry run python manage.py check
```

### 2) Create new migrations (after model changes)
```bash
poetry run python manage.py makemigrations
```

### 3) Apply migrations
```bash
poetry run python manage.py migrate
```

### Collection + Environment
Use the shared Postman workspace/collection (includes my local environment configuration):
- [Postman Collection (SoftDesk API) — includes local environment](https://interstellar-star-493731.postman.co/workspace/SoftDesk-API~8a2188ca-2323-432b-a184-9a94bf963e76/collection/39605256-b2d1c7eb-3e25-4a88-9889-6737e42b46ba?action=share&creator=39605256&active-environment=39605256-88b00cb9-a149-4b2d-9248-df5250808ff7)


### OpenAPI (drf-spectacular)
Regenerate the OpenAPI schema used for Postman import:
```bash
python manage.py spectacular --validate --file postman/openapi.yaml
```
The schema file is saved in:
`postman/openapi.yaml`

## Project Structure
```text
.
├── .github/                       # GitHub automation & project management
│   ├── ISSUE_TEMPLATE/            # Issue templates (epics / technical tasks / user stories)
│   └── workflows/                 # CI pipeline (GitHub Actions)
├── apps/                          # Django apps (domain modules)
│   ├── auth/                      # Authentication (JWT login/refresh/logout endpoints)
│   ├── comments/                  # Comments domain (global comment endpoints + permissions)
│   ├── issues/                    # Issues domain (issues CRUD, assignments, nested comments, etc.)
│   ├── projects/                  # Projects domain (projects CRUD, contributors, nested issues)
│   ├── users/                     # Custom user model + profile endpoints + signup contract
│   └── __init__.py
├── common/                        # Shared utilities used across apps
│   ├── paginator.py               # DRF pagination helpers
│   ├── permissions.py             # Reusable permission classes (object + role based)
│   └── validators.py              # Reusable validators (field/business rules)
├── config/                        # Django project configuration (settings + URL routing)
│   ├── api/                       # API versioning entrypoints
│   │   └── v1/                    # /api/v1/ routes aggregation
│   ├── settings.py                # Django settings (installed apps, DRF, JWT, etc.)
│   ├── urls.py                    # Root URL dispatcher
│   ├── asgi.py                    # ASGI entrypoint (async deployments)
│   └── wsgi.py                    # WSGI entrypoint (classic deployments)
├── postman/                       # API tooling (exports/imports)
│   └── openapi.yaml               # Generated OpenAPI schema (drf-spectacular) for Postman import
├── .env.local                     # Local environment variables (never commit secrets)
├── pyproject.toml                 # Project config (dependencies, ruff, pytest, tooling)
├── poetry.lock                    # Locked dependency versions (Poetry)
├── pytest.ini                     # Pytest configuration
└── README.md                      # Project documentation
```

## Security (OWASP-inspired protections)

This project applies OWASP-inspired protections through a pragmatic “AAA” approach:
Authentication (JWT), Authorization (role/object-level rules), and Accounting/traceability
(consistent rules enforced at the API boundary).

### A01/A07 — Broken Access Control (Authorization)
Access is restricted by default and scoped to the authenticated user:
- Global DRF default permission is `IsAuthenticated` to avoid exposing endpoints publicly.
- Object-level permissions restrict sensitive actions (update/delete) to the resource owner
  or staff where applicable (ex: `IsSelfOrAdmin`, `IsCommentAuthorOrStaff`).
- Querysets are scoped to prevent data leakage (ex: non-staff users only see their own comments),
  which commonly results in 404 for unauthorized objects (preferred to avoid confirming existence).

### A02 — Cryptographic failures (password handling)
- Passwords are stored hashed using Django’s authentication system.
- Password validation rules are enforced through Django’s built-in validators
  (`AUTH_PASSWORD_VALIDATORS`).

### A03 — Injection (input validation + ORM usage)
Injection risks are reduced by:
- Using Django ORM queries instead of raw SQL (prevents most SQL injection patterns by design).
- Validating incoming data at the serializer/model level before persisting:
  - Centralized business validation helpers in `common/validators.py`
    (ex: birth date / minimum age, “exactly one field must be provided”).
  - Serializer validation methods for request-specific rules (ex: assignee validation logic).
- Enforcing uniqueness at the database/model level (constraints) to prevent duplicate rows,
  reducing the need for query-time deduplication with `.distinct()`.

### JWT hardening (authentication lifecycle)
- JWT auth uses access/refresh tokens with rotation + blacklist:
  - Access tokens are short-lived to limit the blast radius if compromised.
  - Refresh token rotation and blacklisting help invalidate tokens after logout/rotation.
- DRF authentication is configured to use JWT by default; SessionAuth is enabled only in DEBUG
  to support the browsable API locally without weakening production defaults.


## Green Code (performance/efficiency)

This project integrates “Green Code” principles by limiting unnecessary computation,
database load, and payload size—especially on list endpoints.

### Pagination to prevent heavy list responses
Pagination is enforced globally to avoid returning large collections in a single response:
- `common/paginator.py` defines `DefaultPagination`:
  - Default `page_size = 10`
  - Optional `page_size` query parameter (capped with `max_page_size = 100`)
- `config/settings.py` applies it globally via:
  - `REST_FRAMEWORK["DEFAULT_PAGINATION_CLASS"] = "common.paginator.DefaultPagination"`

Impact:
- reduces CPU/memory usage on the API server
- reduces database load
- reduces network transfer size for clients

### Query efficiency (reduce N+1 queries and heavy deduplication)
Performance-oriented choices were made to reduce database round-trips and query cost:
- Prefer `select_related()` for single-valued relations (FK/OneToOne) to avoid N+1 queries.
- Use `annotate()` for aggregate values (ex: counts) to compute summaries in SQL instead of Python.
- Reduced usage of `.distinct()` by relying on model/database constraints to prevent duplicate
  rows at write-time, avoiding expensive query-time deduplication.

These optimizations improve response times and reduce compute overhead, aligning with
a “Green Code” approach without premature micro-optimization.

## Quality checks (CI)

### Lint (Ruff)
```bash
poetry run ruff check .
```

### Format check (fails if formatting differs)
```bash
poetry run ruff format . --check
```

### Auto-format (applies formatting)
```bash
poetry run ruff format .
```

### Run tests
```bash
poetry run pytest
```

### Run tests + coverage (terminal + HTML report)
```bash
rm -f .coverage coverage.xml && rm -rf htmlcov
poetry run pytest --cov=apps --cov=common --cov-report=term-missing --cov-report=xml:coverage.xml --cov-report=html

```

## Coverage reports

- Terminal coverage summary: printed in the console
- HTML report: generated in `htmlcov/` (open `htmlcov/index.html`)
