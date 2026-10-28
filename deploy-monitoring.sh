#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

# Las reglas de alerta y el dashboard se leen de monitoring/ para no duplicarlos
kubectl create configmap prometheus-rules \
  --from-file=alerts.yml=monitoring/alerts.yml \
  --dry-run=client -o yaml | kubectl apply -f -
kubectl create configmap grafana-dashboards \
  --from-file=notes-api.json=monitoring/grafana/dashboards/notes-api.json \
  --dry-run=client -o yaml | kubectl apply -f -

kubectl apply -f k8s/monitoring/prometheus.yaml
kubectl apply -f k8s/monitoring/grafana.yaml
kubectl rollout restart deployment/prometheus deployment/grafana
