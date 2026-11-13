#!/bin/sh
curl -fsS "http://127.0.0.1:${PORT:-8000}/healthz" >/dev/null || exit 1
