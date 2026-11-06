# Deployment runbook

Companion to `architecture.md` §9. Commands assume `kubectl` access to the target cluster, an ingress-nginx
controller, and cert-manager with a `letsencrypt-prod` ClusterIssuer (adapt `k8s/base/ingress.yaml` otherwise).

## 0. Before the first public deployment

1. **Revoke the old Firebase service-account key** (`lumiere-583de-firebase-adminsdk-…`). It was committed to the
   repository and is still in git history; assume it is compromised. Remove the history with `git filter-repo` if the
   repository is or will be public.
2. Pick a hostname and point DNS at the ingress.
3. Provision PostgreSQL 16 (managed service recommended) with automated backups and TLS.

## 1. Build and publish the image

CI (`.github/workflows/ci.yml`) builds and pushes `ghcr.io/<owner>/lumieree:<git-sha>` and `:latest` from `main`.
To build locally:

```bash
docker build -t ghcr.io/<owner>/lumieree:dev .
# behind a TLS-inspecting proxy: docker build --secret id=pip_ca,src=/path/to/ca-bundle.crt .
```

## 2. Local run with docker compose

```bash
export BOOTSTRAP_ADMIN_USERNAME=admin BOOTSTRAP_ADMIN_PASSWORD='choose-a-long-password'
docker compose up --build        # http://localhost:8080  (db -> migrate -> web)
```

## 3. Kubernetes

```bash
kubectl apply -f k8s/base/namespace.yaml

# Secrets (never commit real values)
kubectl -n lumieree create secret generic lumieree-secrets \
  --from-literal=SECRET_KEY="$(openssl rand -hex 32)" \
  --from-literal=DATABASE_URL='postgresql+psycopg://USER:PASSWORD@HOST:5432/lumieree?sslmode=require' \
  --from-literal=BOOTSTRAP_ADMIN_USERNAME=admin \
  --from-literal=BOOTSTRAP_ADMIN_PASSWORD='<long random password>'
```

Edit `k8s/overlays/production/kustomization.yaml` (hostname, image tag), then for every release:

```bash
TAG=<git-sha>
# 1. migrate first (Jobs are immutable, so replace it)
kubectl -n lumieree delete job lumieree-migrate --ignore-not-found
sed "s#ghcr.io/ryan-wong123/lumieree:latest#ghcr.io/<owner>/lumieree:${TAG}#" k8s/base/migrate-job.yaml | kubectl apply -f -
kubectl -n lumieree wait --for=condition=complete job/lumieree-migrate --timeout=300s

# 2. roll out the app
(cd k8s/overlays/production && kustomize edit set image lumieree=ghcr.io/<owner>/lumieree:${TAG})
kubectl apply -k k8s/overlays/production
kubectl -n lumieree rollout status deploy/lumieree-web
```

In-cluster PostgreSQL instead of a managed one: create `postgres-credentials` (`POSTGRES_PASSWORD`), use
`postgresql+psycopg://lumieree:<password>@postgres:5432/lumieree` as `DATABASE_URL`, and apply
`k8s/overlays/in-cluster-postgres` instead of `overlays/production`. Copy `postgres-backups` dumps off-cluster.

Smoke test: `https://<host>/healthz` → `ok`, `/readyz` → `ready`, sign in as the bootstrap admin.

## 4. Importing the legacy Firebase data (once)

```bash
pip install -r requirements-migrate.txt
export DATABASE_URL=...            # the new PostgreSQL
flask --app wsgi db upgrade
flask --app wsgi import-firestore --credentials /secure/path/firebase-key.json --dry-run   # rehearsal
flask --app wsgi import-firestore --credentials /secure/path/firebase-key.json
```

The command writes `migrated-credentials.csv` (mode 600) with a random temporary password per user. Distribute them
securely, then delete the file. Users must choose a new password at first login. Firestore `prescriptions` (legacy,
no UI) are not migrated.

## 5. Rollback

* App only: `kubectl -n lumieree rollout undo deploy/lumieree-web`.
* Schema: migrations are expand/contract, so the previous image keeps working with the new schema for one release.
  Only run `flask db downgrade` after taking a backup and confirming no data depends on the change.

## 6. Backup and restore (PostgreSQL)

```bash
pg_dump --format=custom --file=lumieree.dump "$DATABASE_URL_PLAIN"
pg_restore --clean --if-exists --no-owner --dbname "$TARGET_URL" lumieree.dump
```

Test a restore regularly. Managed services: enable point-in-time recovery.

## 7. Creating or resetting accounts

* Clinic accounts: sign in as super admin → *Super Admin* → *Create new user* (they must change the temporary password).
* Lost super-admin access: `kubectl -n lumieree exec deploy/lumieree-web -- flask create-super-admin`.

## 8. Hardening checklist

- [ ] `SECRET_KEY` random (≥ 32 chars) and stored only in the cluster Secret
- [ ] Database not reachable from the internet; TLS to the database
- [ ] Ingress forces HTTPS; `TRUSTED_PROXY_COUNT` matches the number of proxies
- [ ] Redis reachable only from the web pods (NetworkPolicy provided)
- [ ] Image tags are immutable (git SHA); images scanned in CI/registry
- [ ] Backups tested; dumps stored off-cluster
- [ ] Old Firebase key revoked
