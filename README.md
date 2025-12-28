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

### 2) Run the API (dev)
```bash
poetry run python manage.py runserver
```

### 3) Run lint
```bash
poetry run ruff check .
```

### 4) Run tests
```bash
poetry run pytest
```

## Postman
A Postman collection + environments will live in:
- `postman/ (to be added)

## Project Structure (high-level)
- `config/` : Django project settings + root urls

- `api/v1/` : versioned API routing entrypoint

- `apps/` : domain apps (users, projects, issues, comments)

- `.github/workflows/` : CI pipeline
