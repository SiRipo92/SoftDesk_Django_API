# SoftDesk Support — Secure REST API (Django REST Framework)
![CI](https://github.com/SiRipo92/SoftDesk_Django_API/actions/workflows/ci.yml/badge.svg)
![Ruff](https://img.shields.io/badge/linted%20with-ruff-261230.svg)

School project: build a secure REST API with JWT auth, role-based permissions, OWASP-inspired protections, and test strategy (Postman + automated tests).

## Tech stack
- Python 3.12
- Django + Django REST Framework
- SimpleJWT (access/refresh + blacklist)
- Poetry (dependency management)
- Ruff (lint + format)
- Pytest + pytest-django (+ pytest-cov for coverage)
- GitHub Actions (CI: lint + format check + tests + coverage artifacts)

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

## Postman
A Postman collection + environments will live in:
- `postman/ (to be added)

## Project Structure
```text
.
├── apps/                       # Domain apps (business modules)
│   ├── auth/                   # JWT login/refresh/logout (blacklist)
│   │   ├── urls.py
│   │   ├── views.py
│   │   └── tests.py
│   ├── users/                  # User CRUD + permissions + serializers
│   │   ├── models.py
│   │   ├── serializers.py
│   │   ├── urls.py
│   │   ├── views.py
│   │   └── tests.py
│   ├── projects/               # Projects + contributor management
│   │   ├── models.py
│   │   ├── serializers.py
│   │   ├── urls.py
│   │   ├── views.py
│   │   └── tests.py
│   ├── issues/                 # Issues domain (WIP)
│   └── comments/               # Comments domain (WIP)
├── common/                     # Shared utilities (permissions, validators, pagination, throttling)
│   ├── permissions.py
│   ├── validators.py
│   ├── paginator.py
│   └── throttling.py
├── config/                     # Django project config
│   ├── settings.py
│   ├── urls.py
│   └── api/v1/urls.py          # Versioned API routing entrypoint
├── postman/                    # Postman collection + environments
├── manage.py
├── pyproject.toml              # Poetry + tooling config (ruff, pytest, coverage)
└── .github/workflows/ci.yml    # CI pipeline (lint + tests + coverage)
```

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
