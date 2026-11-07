#!/usr/bin/env bash
# Rollback drill: proves that a bad release is rolled back and the previous version keeps serving, WITHOUT touching
# the real application. It runs in a throwaway namespace (`rollback-drill`) with a tiny stand-in web app
# (busybox httpd, 2 replicas, same rolling-update settings as the real Deployment), ships two kinds of bad release
# (an image that does not exist, and a pod that never becomes ready), applies the same rollback commands that
# deploy/deploy.sh uses (`kubectl rollout undo` + `rollout status`), and probes the service every half second throughout.
#
#   bash deploy/rollback-drill.sh        # on the server, as a user that can run kubectl (see docs/deployment.md §17)
#
# Exit status 0 and the last line `DRILL_PASSED` mean: both bad releases were detected, both were rolled back, the
# service answered with the old version afterwards and not a single probe failed while it happened.
# Not covered: the migration step, the real image, or the smoke test inside deploy.sh (those run on every real release).
set -euo pipefail

export KUBECONFIG="${KUBECONFIG:-$HOME/.kube/config}"
NS=rollback-drill
GOOD_IMAGE="${DRILL_IMAGE:-busybox:1.36}"
BAD_IMAGE="busybox:this-tag-does-not-exist"
ROLLOUT_TIMEOUT="${DRILL_TIMEOUT:-45s}"
probe_log="$(mktemp)"
probe_pid=""

cleanup() {
  [ -z "$probe_pid" ] || kill "$probe_pid" 2>/dev/null || true
  kubectl delete ns "$NS" --wait=false >/dev/null 2>&1 || true
  rm -f "$probe_log"
}
trap cleanup EXIT

fail() { echo "DRILL_FAILED: $1" >&2; exit 1; }

# One Deployment definition for every "release": image, version label and the path the readiness probe checks.
release() {
  local image="$1" version="$2" ready_path="$3"
  kubectl -n "$NS" apply -f - >/dev/null <<EOF
apiVersion: apps/v1
kind: Deployment
metadata: {name: drill-web}
spec:
  replicas: 2
  strategy: {type: RollingUpdate, rollingUpdate: {maxUnavailable: 0, maxSurge: 1}}
  selector: {matchLabels: {app: drill-web}}
  template:
    metadata: {labels: {app: drill-web}}
    spec:
      containers:
        - name: web
          image: $image
          command: ["sh", "-c", "mkdir -p /www && echo release-$version > /www/index.html && exec httpd -f -p 8080 -h /www"]
          ports: [{containerPort: 8080}]
          readinessProbe:
            httpGet: {path: $ready_path, port: 8080}
            periodSeconds: 2
          resources: {requests: {cpu: 5m, memory: 8Mi}, limits: {cpu: 100m, memory: 32Mi}}
---
apiVersion: v1
kind: Service
metadata: {name: drill-web}
spec:
  selector: {app: drill-web}
  ports: [{port: 8080, targetPort: 8080}]
EOF
}

running_image() { kubectl -n "$NS" get deploy drill-web -o jsonpath='{.spec.template.spec.containers[0].image}'; }
served() { curl -fsS --max-time 2 "http://$SVC_IP:8080/" 2>/dev/null || true; }

# The same sequence deploy.sh runs when a rollout or smoke test fails.
rollback() {
  echo "-- rollout failed as expected; rolling back"
  kubectl -n "$NS" rollout undo deploy/drill-web >/dev/null
  kubectl -n "$NS" rollout status deploy/drill-web --timeout="$ROLLOUT_TIMEOUT" >/dev/null || fail "rollback did not complete"
}

bad_release() {
  local name="$1" image="$2" version="$3" ready_path="$4"
  echo "== bad release: $name"
  release "$image" "$version" "$ready_path"
  if kubectl -n "$NS" rollout status deploy/drill-web --timeout="$ROLLOUT_TIMEOUT" >/dev/null 2>&1; then
    fail "the bad release '$name' was NOT detected (rollout reported success)"
  fi
  rollback
  [ "$(running_image)" = "$GOOD_IMAGE" ] || fail "after rollback the image is '$(running_image)', expected '$GOOD_IMAGE'"
  [ "$(served)" = "release-1" ] || fail "after rollback the service does not serve release-1 (got '$(served)')"
  echo "   ok: rolled back to $GOOD_IMAGE and still serving release-1"
}

kubectl delete ns "$NS" --ignore-not-found --wait=true >/dev/null 2>&1 || true
kubectl create ns "$NS" >/dev/null

echo "== release 1 (healthy)"
release "$GOOD_IMAGE" 1 /
kubectl -n "$NS" rollout status deploy/drill-web --timeout=120s >/dev/null || fail "the healthy release did not start"
SVC_IP="$(kubectl -n "$NS" get svc drill-web -o jsonpath='{.spec.clusterIP}')"
[ "$(served)" = "release-1" ] || fail "release 1 does not answer"
echo "   ok: serving release-1 at $SVC_IP"

# Probe the service continuously while the bad releases come and go.
( while true; do if curl -fsS --max-time 2 "http://$SVC_IP:8080/" >/dev/null 2>&1; then echo ok; else echo fail; fi; sleep 0.5; done ) >"$probe_log" &
probe_pid=$!

bad_release "image that does not exist" "$BAD_IMAGE" 2 /
release "$GOOD_IMAGE" 1 /      # back to a clean baseline revision for the second drill
kubectl -n "$NS" rollout status deploy/drill-web --timeout="$ROLLOUT_TIMEOUT" >/dev/null || fail "could not return to the baseline"
bad_release "pod that never becomes ready" "$GOOD_IMAGE" 3 /missing-health-endpoint

kill "$probe_pid" 2>/dev/null || true
probe_pid=""
ok="$(grep -c '^ok$' "$probe_log" || true)"
bad="$(grep -c '^fail$' "$probe_log" || true)"
echo "== service probes during the drill: $ok ok, $bad failed"
[ "$bad" = "0" ] || fail "$bad probe(s) failed: users would have seen errors during the bad releases"
[ "$ok" -gt 10 ] || fail "too few probes ran ($ok) to prove anything"
echo "DRILL_PASSED"
