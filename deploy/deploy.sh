#!/usr/bin/env bash
# Deploy one commit of Lumieree to the local k3s cluster (AWS reference deployment).
#
# Normally run by the SSM document `lumieree-deploy` after CI publishes the image (see docs/deployment.md §17):
#   bash deploy/deploy.sh <40-character git commit sha>
# It runs on the server as the `ubuntu` user, from a checkout of that same commit, so the script that deploys a
# release is always the reviewed one from the release itself.
#
# Steps: check the image exists -> run the database migration (expand-only, the old pods keep working) ->
# roll out the new image -> check the rollout and the running image -> smoke test /readyz through the ingress.
# If the rollout or the smoke test fails, the Deployment is rolled back to the previous revision and the script
# exits non-zero. If the migration fails nothing is rolled out.
set -euo pipefail

TAG="${1:?usage: deploy.sh <40-character git sha>}"
[[ "$TAG" =~ ^[0-9a-f]{40}$ ]] || { echo "refusing to deploy: '$TAG' is not a full git SHA" >&2; exit 2; }

export KUBECONFIG="${KUBECONFIG:-$HOME/.kube/config}"
NS="${DEPLOY_NAMESPACE:-lumieree}"
HOST="${DEPLOY_HOST:-lumieree.duckdns.org}"
IMAGE="${DEPLOY_IMAGE:-ghcr.io/ryan-wong123/lumieree}"

cd "$(git rev-parse --show-toplevel)"
current_image() { kubectl -n "$NS" get deploy lumieree-web -o jsonpath='{.spec.template.spec.containers[0].image}'; }

echo "== deploying $TAG to $HOST"
previous="$(current_image || true)"
echo "previous image: ${previous:-none}"

# 1. The image must already be published (CI pushes it before this runs). The registry is public.
token="$(curl -fsS "https://ghcr.io/token?scope=repository:${IMAGE#ghcr.io/}:pull" | sed -n 's/.*"token":"\([^"]*\)".*/\1/p')"
code="$(curl -s -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $token" \
  -H 'Accept: application/vnd.oci.image.index.v1+json, application/vnd.docker.distribution.manifest.v2+json' \
  "https://ghcr.io/v2/${IMAGE#ghcr.io/}/manifests/$TAG")"
[ "$code" = "200" ] || { echo "image $IMAGE:$TAG is not available in the registry (HTTP $code); aborting" >&2; exit 1; }

# 2. Render the overlay for this release in a scratch copy (tracked files stay untouched).
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
cp -r k8s "$work/k8s"
sed -i "s/CHANGE-ME.duckdns.org/$HOST/g; s#newTag: latest#newTag: $TAG#" "$work/k8s/overlays/aws-k3s/kustomization.yaml"
grep -q "newTag: $TAG" "$work/k8s/overlays/aws-k3s/kustomization.yaml" || { echo "could not set the image tag" >&2; exit 1; }

# 3. Migrate BEFORE switching pods: migrations are expand-only, so the running version keeps working.
kubectl -n "$NS" delete job lumieree-migrate --ignore-not-found
sed "s#$IMAGE:latest#$IMAGE:$TAG#" k8s/base/migrate-job.yaml | kubectl apply -f -
if ! kubectl -n "$NS" wait --for=condition=complete job/lumieree-migrate --timeout=300s; then
  kubectl -n "$NS" logs job/lumieree-migrate --tail=40 || true
  echo "migration failed: nothing was rolled out" >&2
  exit 1
fi
kubectl -n "$NS" logs job/lumieree-migrate --tail=5

rollback() {
  echo "!! $1: rolling back to ${previous:-the previous revision}" >&2
  kubectl -n "$NS" rollout undo deploy/lumieree-web || true
  kubectl -n "$NS" rollout status deploy/lumieree-web --timeout=300s || true
  echo "ROLLED_BACK" >&2
  exit 1
}

# 4. Roll out and check the Deployment really runs the new image (guards against a silently ignored tag).
kubectl apply -k "$work/k8s/overlays/aws-k3s" >/dev/null
kubectl -n "$NS" rollout status deploy/lumieree-web --timeout=300s || rollback "rollout did not finish"
running="$(current_image)"
[ "$running" = "$IMAGE:$TAG" ] || rollback "running image is '$running', expected '$IMAGE:$TAG'"

# 5. Smoke test through the real ingress (TLS + routing + app + database), from the server itself. k3s publishes
#    the ingress on the node's own address (not on 127.0.0.1), so point the hostname at that address.
node_ip="$(hostname -I | awk '{print $1}')"
smoke() { curl -fsS --max-time 5 --resolve "$HOST:443:$node_ip" "https://$HOST$1"; }
ok=""
for _ in $(seq 1 30); do
  if smoke /readyz | grep -q '"ready"'; then ok=1; break; fi
  sleep 5
done
[ -n "$ok" ] || rollback "/readyz did not report ready"
smoke /healthz | grep -q '"ok"' || rollback "/healthz failed"

kubectl -n "$NS" get pods
echo "DEPLOY_OK $TAG"
