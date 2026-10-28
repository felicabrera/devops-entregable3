#!/usr/bin/env bash
set -euo pipefail

kubectl patch service devops-app \
  -p '{"spec":{"selector":{"app":"devops-app","version":"green"}}}'

echo "Service devops-app now routes traffic to version: green"
