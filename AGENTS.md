# AGENTS.md – instructions for AI coding agents (and humans) working on Lumieree

Lumieree is a multi-tenant Flask + PostgreSQL clinic POS. Read `PRD.md` (what/why) and `architecture.md` (how)
before changing anything. These files are the project's memory: **they must always describe the code as it is.**

## 1. Documentation sync protocol (mandatory)

Whenever you change the codebase, update the documentation **in the same change set**, before you say you are done.

### 1.1 What to update

| You changed… | Update in `architecture.md` | Update in `PRD.md` |
| --- | --- | --- |
| A route / URL / HTTP method / access level | §5 Route inventory (exact `rule` string, methods, access) | Affected requirement(s) in §4 |
| A model, column, constraint, index, or a migration | §6 Data model (+ ERD) | Data-related requirements; §10 if a limitation is removed |
| An environment variable / config default | §8 Configuration table; also `.env.example`, `k8s/base/configmap.yaml` or the Secret template if relevant | §6 if deployment needs change |
| Authentication, roles, permissions, session rules | §4 Request lifecycle, §7 Security architecture | §2 Roles, §4.1 AUTH-* |
| A user-visible feature, page, wording of a rule, validation | §3/§5 if structure changed | §3 Journeys, §4 Requirements (add/modify IDs), §10 roadmap |
| A dependency, Dockerfile, compose file, `k8s/`, CI workflow | §2 Stack, §9 Deployment, §11 CI | §6 Release requirements |
| A blueprint/module (added, renamed, removed) | §3 Repository layout | – |
| A CLI command | §5 CLI list | §4.1 / §4.9 if user-facing |
| A decision with trade-offs (library, pattern, policy) | §13 Decision log | §9 Resolved decisions |
| A limitation fixed or discovered | §7 "Known gaps" | §10 Known limitations and roadmap |

### 1.2 How to update

1. Edit the affected sections so they are **accurate and minimal** – never leave stale statements or TODO markers.
2. Append one row to the **Change log** at the bottom of each file you touched (date `YYYY-MM-DD`, one sentence).
3. Bump `Last reviewed:` at the top of `architecture.md` / `PRD.md` when you edited them.
4. Keep requirement IDs stable (`AUTH-3`, `FD-2`, …). Add new IDs; do not renumber. Mark removed behaviour as removed
   in the change log rather than silently deleting history.
5. Run the checks (§3). They must pass before you finish.

### 1.3 Automatic enforcement (do not bypass)

* `tests/test_docs.py` fails if any route, table, CLI command, blueprint module or environment variable exists in code
  but not in `architecture.md`, or if `architecture.md` lists a route that no longer exists.
* `scripts/check_docs_updated.py` fails when files that affect product/architecture changed but `PRD.md` /
  `architecture.md` did not:
  * Claude Code runs it from `.claude/settings.json` (Stop hook) and keeps you working until docs are updated;
  * CI runs it on pull requests (`docs-in-sync` job);
  * optional local hook: `git config core.hooksPath .githooks`.
* Escape hatch only for changes that alter neither behaviour nor structure (formatting, comments, tests): add the
  line `Docs-Not-Needed: <reason>` to a commit message (CI) or set `DOCS_CHECK_SKIP=1` locally. Never use it to skip
  documenting a real change.

## 2. Project conventions

* **Layout**: Flask application factory (`lumieree/__init__.py`), one blueprint per feature in `lumieree/blueprints/`,
  models in `lumieree/models.py`, helpers in `lumieree/utils.py`. Templates in `templates/`.
* **Multi-tenancy (critical)**: every row has `owner_id`. Always query with `Model.owned_by(current_uid())` or
  `Model.get_owned(current_uid(), id)`. Never fetch by id alone. Never accept `owner_id`, `id` or other column names
  from a form – parse explicit whitelisted fields (see `_patient_from_form`, `_medicine_from_form`).
* **Security rules**: all state-changing routes are `POST` with CSRF (`<input name="csrf_token" value="{{ csrf_token() }}">`
  in forms; `X-CSRFToken` header for `fetch`). No secrets in the repo, no `debug=True`, no `|safe` on user data,
  no string-built HTML in JS (use DOM APIs), no raw SQL string formatting. Redirect targets must pass `is_safe_next`.
  Role checks use `@admin_required` / `@super_admin_required`; authentication is enforced globally in
  `auth._load_user`.
* **Validation**: use `utils.clean/to_int/to_decimal/parse_date`; invalid input must produce a flash message and a
  400/redirect, never a 500.
* **Database changes**: edit `models.py`, then `flask db migrate -m "…"`, review the generated file in
  `migrations/versions/` (rename it `NNNN_description.py`, set a readable revision id), test `upgrade` / `downgrade`,
  and keep migrations backward compatible for one release (expand → deploy → contract).
* **i18n**: add every new UI string to **both** `en` and `zh` in `lumieree/translations.py`.
* **Style**: `ruff check .` and `ruff format .` (line length 120). Type hints on new code. Small functions.
* **Commits**: author is the human developer; do not add AI co-author trailers or AI names to commits, PR text, or
  code comments unless the maintainer asks. Conventional, imperative subject lines.

## 3. Commands

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt

ruff check . && ruff format --check .             # lint
pytest                                            # tests (SQLite)
TEST_DATABASE_URL=postgresql+psycopg://lumieree:lumieree@localhost:5432/lumieree_test pytest   # tests (PostgreSQL)
python scripts/check_docs_updated.py --working-tree   # docs gate for uncommitted work

docker compose up --build                         # app on http://localhost:8080 (+ PostgreSQL, migrations)
flask --app wsgi db upgrade                       # apply migrations
flask --app wsgi create-super-admin               # interactive first admin
```

## 4. Definition of done

- [ ] Behaviour implemented and covered by tests (add tenant-isolation tests for any new data access).
- [ ] `ruff check`, `ruff format --check`, `pytest` all pass.
- [ ] New migration included when the schema changed, and `flask db check` reports no drift.
- [ ] `PRD.md` and `architecture.md` updated per §1, including both Change logs.
- [ ] No secrets, keys, `.env` files or personal data committed.
