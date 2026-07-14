#!/usr/bin/env bash
set -euo pipefail

VENV_PYTHON="${HOME}/.venvs/saas_test_comptage/bin/python"

if [[ ! -x "${VENV_PYTHON}" ]]; then
  echo "Python introuvable: ${VENV_PYTHON}" >&2
  exit 1
fi

exec "${VENV_PYTHON}" "$(dirname "$0")/split_plan_image.py" "$@"
