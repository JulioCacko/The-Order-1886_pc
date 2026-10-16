#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-or-later
set -euo pipefail
case ${OSTYPE:-} in msys*|cygwin*) export PATH="/usr/bin:$PATH" ;; esac
cd -- "$(dirname -- "$0")"
source ./msys2-env.sh
exec "${PYTHON:-python3}" order1886.py "$@"
