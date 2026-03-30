#!/usr/bin/env bash
set -euo pipefail

echo "=== Running tests with coverage ==="
poetry run pytest \
    --cov=zamp_sdk \
    --cov-report=xml \
    --cov-report=term-missing \
    --cov-fail-under=80

CHANGED_LINES=$(git diff --stat origin/main -- '*.py' | tail -1 | grep -oP '\d+(?= insertion)' || echo "0")

if [ "$CHANGED_LINES" -gt 30 ]; then
    echo "=== Running diff-cover (fail-under=80) ==="
    poetry run diff-cover coverage.xml --compare-branch=origin/main --fail-under=80
else
    echo "=== Skipping diff-cover ($CHANGED_LINES changed lines < 30 threshold) ==="
fi
