# Lumieree

Multi-tenant point-of-sale and clinic-management web app for Traditional Chinese Medicine clinics: patients, visits
and prescriptions, front-desk dispensing queue, medicine inventory (with barcode scanning and CSV import),
appointments, bilingual (English / 中文) PDF receipts, and an admin dashboard.

Stack: Python 3.13 · Flask · PostgreSQL 16 · SQLAlchemy 2 / Alembic · Docker · Kubernetes.

## Quick start

```bash
export BOOTSTRAP_ADMIN_USERNAME=admin BOOTSTRAP_ADMIN_PASSWORD='choose-a-long-password'
docker compose up --build
# open http://localhost:8080 and sign in with the bootstrap admin
```

Without Docker:

```bash
python -m venv .venv && . .venv/bin/activate && pip install -r requirements-dev.txt
cp .env.example .env            # set DATABASE_URL to a local PostgreSQL
export $(grep -v '^#' .env | xargs)
flask --app wsgi db upgrade
flask --app wsgi create-super-admin
flask --app wsgi run --port 8080
```

## Tests and quality

```bash
ruff check . && ruff format --check .
pytest                                                    # SQLite
TEST_DATABASE_URL=postgresql+psycopg://user:pw@localhost/lumieree_test pytest   # PostgreSQL
```

## Documentation

| Doc | Purpose |
| --- | --- |
| [`PRD.md`](PRD.md) | Product requirements: users, journeys, requirements, roadmap |
| [`architecture.md`](architecture.md) | System design, data model, security, configuration, deployment |
| [`docs/deployment.md`](docs/deployment.md) | Runbook: AWS (EC2 + k3s + S3 backups) with a DuckDNS domain, Firebase import, backups, teardown |
| [`AGENTS.md`](AGENTS.md) | Rules for AI agents and contributors, including the mandatory docs-sync protocol |

`PRD.md` and `architecture.md` are kept in sync with the code automatically (tests, a pre-commit/CI check, and a
Claude Code hook); see `AGENTS.md`.
