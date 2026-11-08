#!/usr/bin/env bash
# Guarded Helm delivery: upgrade -> helm test -> semantic smoke -> (rollback on failure).
#
# Required env: RELEASE, ENVIRONMENT, IMAGE_REPOSITORY, IMAGE_DIGEST
# Optional env: KUBE_NAMESPACE, RANKING_MODE, BUILD_REVISION, REPORT_DIR,
#               CHART, HELM_TIMEOUT, SMOKE_PORT, HELM_DRIVER
#
# Exit codes:
#   0  release deployed and verified
#   1  release rejected, rolled back to the last good revision and re-verified
#   2  release rejected and could NOT be recovered (no good revision / rollback failed)
set -uo pipefail

: "${RELEASE:?RELEASE is required}"
: "${ENVIRONMENT:?ENVIRONMENT is required}"
: "${IMAGE_REPOSITORY:?IMAGE_REPOSITORY is required}"
: "${IMAGE_DIGEST:?IMAGE_DIGEST is required}"

NAMESPACE="${KUBE_NAMESPACE:-mlops-students}"
RANKING_MODE="${RANKING_MODE:-normal}"
BUILD_REVISION="${BUILD_REVISION:-unknown}"
REPORT_DIR="${REPORT_DIR:-reports/${ENVIRONMENT}}"
CHART="${CHART:-helm/mlops-search}"
HELM_TIMEOUT="${HELM_TIMEOUT:-5m}"
SMOKE_PORT="${SMOKE_PORT:-18090}"
export HELM_DRIVER="${HELM_DRIVER:-configmap}"

FULLNAME="${RELEASE}-mlops-search"
mkdir -p "$REPORT_DIR"
exec > >(tee -a "$REPORT_DIR/deploy.log") 2>&1

log() { printf '[%s] %s\n' "$(date -u +%H:%M:%SZ)" "$*"; }
section() { printf '\n========== %s ==========\n' "$*"; }

show_history() {
  helm history "$RELEASE" -n "$NAMESPACE" --max 20 2>/dev/null || echo "(release $RELEASE has no history yet)"
}

last_deployed_revision() {
  helm history "$RELEASE" -n "$NAMESPACE" --max 100 -o json 2>/dev/null \
    | python3 -c 'import json,sys
h = json.load(sys.stdin)
d = [r["revision"] for r in h if r.get("status") == "deployed"]
print(d[-1] if d else "")' 2>/dev/null || true
}

# Ждем, пока у release останутся только pod-ы текущего ReplicaSet,
# чтобы port-forward не попал в завершающийся pod предыдущей ревизии.
wait_settled() {
  kubectl -n "$NAMESPACE" rollout status "deployment/$FULLNAME" --timeout=180s || return 1
  for _ in $(seq 1 60); do
    terminating=$(kubectl -n "$NAMESPACE" get pods \
      -l "app.kubernetes.io/name=mlops-search,app.kubernetes.io/instance=$RELEASE" \
      -o jsonpath='{range .items[*]}{.metadata.deletionTimestamp}{"\n"}{end}' | grep -c . || true)
    [ "$terminating" = "0" ] && return 0
    sleep 2
  done
  log "WARNING: old pods are still terminating"
}

smoke() {
  local output="$1"; shift
  python3 scripts/verify_release.py \
    --release "$RELEASE" --namespace "$NAMESPACE" --port "$SMOKE_PORT" \
    --request-id "smoke-${ENVIRONMENT}-$(date +%s)" \
    --expect-environment "$ENVIRONMENT" --output "$output" "$@"
}

section "Release plan"
log "release=$RELEASE namespace=$NAMESPACE environment=$ENVIRONMENT"
log "image=${IMAGE_REPOSITORY}@${IMAGE_DIGEST} rankingMode=$RANKING_MODE revision=$BUILD_REVISION"

section "helm history BEFORE"
show_history | tee "$REPORT_DIR/helm-history-before.txt"

LAST_GOOD="$(last_deployed_revision)"
echo "${LAST_GOOD:-none}" > "$REPORT_DIR/last-good-revision.txt"
log "last good (deployed) revision: ${LAST_GOOD:-none}"

HELM_ARGS=(
  --set-string "image.repository=${IMAGE_REPOSITORY}"
  --set-string "image.digest=${IMAGE_DIGEST}"
  --set-string "environment=${ENVIRONMENT}"
  --set-string "rankingMode=${RANKING_MODE}"
  --set-string "buildRevision=${BUILD_REVISION}"
)

section "helm lint"
helm lint "$CHART" "${HELM_ARGS[@]}" || { log "helm lint failed, nothing deployed"; exit 2; }

FAILED_STAGE=""

section "helm upgrade --install"
if ! helm upgrade --install "$RELEASE" "$CHART" -n "$NAMESPACE" \
      --wait --timeout "$HELM_TIMEOUT" --history-max 20 "${HELM_ARGS[@]}"; then
  FAILED_STAGE="helm upgrade"
fi

if [ -z "$FAILED_STAGE" ]; then
  wait_settled || FAILED_STAGE="rollout"
fi

if [ -z "$FAILED_STAGE" ]; then
  section "helm test"
  helm test "$RELEASE" -n "$NAMESPACE" --logs --timeout 3m || FAILED_STAGE="helm test"
fi

if [ -z "$FAILED_STAGE" ]; then
  section "semantic smoke"
  smoke "$REPORT_DIR/smoke.json" --expect-digest "$IMAGE_DIGEST" || FAILED_STAGE="semantic smoke"
fi

if [ -z "$FAILED_STAGE" ]; then
  kubectl -n "$NAMESPACE" get deployment "$FULLNAME" \
    -o jsonpath='{.spec.template.spec.containers[0].image}{"\n"}' | tee "$REPORT_DIR/deployment-image.txt"
  section "helm history AFTER"
  show_history | tee "$REPORT_DIR/helm-history-after.txt"
  log "RELEASE VERIFIED: $RELEASE ($ENVIRONMENT)"
  exit 0
fi

section "ROLLBACK"
echo "::error::release $RELEASE rejected at stage: $FAILED_STAGE"
log "release rejected at stage: $FAILED_STAGE"
if [ -z "$LAST_GOOD" ]; then
  log "no previous good revision, rollback impossible"
  show_history | tee "$REPORT_DIR/helm-history-after.txt"
  exit 2
fi

log "helm rollback $RELEASE $LAST_GOOD"
if ! helm rollback "$RELEASE" "$LAST_GOOD" -n "$NAMESPACE" --wait --timeout "$HELM_TIMEOUT"; then
  log "helm rollback failed"
  show_history | tee "$REPORT_DIR/helm-history-after.txt"
  exit 2
fi
wait_settled || true

section "semantic smoke AFTER rollback"
RECOVERED=1
smoke "$REPORT_DIR/smoke-after-rollback.json" --expect-ranking-mode normal || RECOVERED=0

VALUES_MODE=$(helm get values "$RELEASE" -n "$NAMESPACE" -o json \
  | python3 -c 'import json,sys; print(json.load(sys.stdin).get("rankingMode", "normal"))')
CONFIG_MODE=$(kubectl -n "$NAMESPACE" get configmap "$FULLNAME" -o jsonpath='{.data.RANKING_MODE}')
log "after rollback: helm values rankingMode=$VALUES_MODE, ConfigMap RANKING_MODE=$CONFIG_MODE"
{ echo "helm_values_rankingMode=$VALUES_MODE"; echo "configmap_RANKING_MODE=$CONFIG_MODE"; } \
  > "$REPORT_DIR/ranking-mode-after-rollback.txt"
[ "$VALUES_MODE" = "normal" ] && [ "$CONFIG_MODE" = "normal" ] || RECOVERED=0

kubectl -n "$NAMESPACE" get deployment "$FULLNAME" \
  -o jsonpath='{.spec.template.spec.containers[0].image}{"\n"}' | tee "$REPORT_DIR/deployment-image.txt"

section "helm history AFTER"
show_history | tee "$REPORT_DIR/helm-history-after.txt"

if [ "$RECOVERED" = "1" ]; then
  log "ROLLBACK VERIFIED: $RELEASE restored to revision $LAST_GOOD with rankingMode=normal"
  exit 1
fi
log "ROLLBACK DID NOT RESTORE A HEALTHY RELEASE"
exit 2
