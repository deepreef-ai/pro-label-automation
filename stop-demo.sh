#!/usr/bin/env bash
# POSIX twin of stop-demo.ps1: stops exactly the PIDs in data/demo.pids (and their children).
source "$(dirname "$0")/infra/demo/demo-lib.sh"
step "Stopping the demo"
stop_all
