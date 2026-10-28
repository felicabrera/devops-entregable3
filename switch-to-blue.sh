#!/usr/bin/env bash
set -euo pipefail

kubectl patch service devops-app \
  -p '{"spec":{"selector":{"app":"devops-app","version":"blue"}}}'

echo "Service devops-app now routes traffic to version: blue"
