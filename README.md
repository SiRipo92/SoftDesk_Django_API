# SoftDesk Support — Secure REST API (Django REST Framework)

School project: build a secure REST API with JWT auth, role-based permissions, OWASP-inspired protections, and test strategy (Postman + automated tests).

## Tech stack
- Python 3.12
- Django + Django REST Framework
- SimpleJWT (access/refresh)
- Poetry (dependency management)
- Ruff (lint)
- Pytest + pytest-django (tests)
- GitHub Actions (CI: lint + tests)

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

## Project Structure (high-level)
- `config/` : Django project settings + root urls

- `api/v1/` : versioned API routing entrypoint

- `apps/` : domain apps (users, projects, issues, comments)

- `.github/workflows/` : CI pipeline
