#!/usr/bin/env bash
set -euo pipefail

install -d -m 0755 /opt/brokerage/revision
install -d -m 0700 /opt/brokerage/config
rm -f -- /opt/brokerage/config/runtime.env
find /opt/brokerage/revision -mindepth 1 -maxdepth 1 -exec rm -rf -- {} +
