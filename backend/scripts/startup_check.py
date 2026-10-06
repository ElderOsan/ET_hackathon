#!/usr/bin/env python
"""Read-only startup diagnostics, run by run.bat/run.sh before uvicorn starts. Prints Python
version, the first free port starting at --base-port (default 8000), and whether
GEMINI_API_KEY is configured (never the value). The run scripts parse the final "PORT=<n>"
line to know which port to actually start uvicorn on and open the browser at -- this is how
a port-8000-already-in-use judge machine gets a working app instead of a crash.
"""
from __future__ import annotations

import argparse
import socket
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def first_free_port(base_port: int, host: str = "127.0.0.1", max_tries: int = 20) -> int:
    for port in range(base_port, base_port + max_tries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind((host, port))
                return port
            except OSError:
                continue
    raise RuntimeError(f"no free port found in range {base_port}-{base_port + max_tries - 1}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-port", type=int, default=8000)
    args = parser.parse_args()

    print("=== Renewable Energy Orchestrator -- startup check ===")

    py_ok = sys.version_info >= (3, 10)
    print(f"Python: {sys.version.split()[0]} ({'OK' if py_ok else 'TOO OLD, needs 3.10+'})")
    if not py_ok:
        print("  -> see README Troubleshooting: 'Python version too old / Python not found'")

    port = first_free_port(args.base_port)
    if port == args.base_port:
        print(f"Port {args.base_port}: free")
    else:
        print(f"Port {args.base_port}: IN USE -- using {port} instead (see README Troubleshooting: 'port already in use')")

    try:
        from app.core.config import GEMINI_API_KEY
        if GEMINI_API_KEY:
            print("GEMINI_API_KEY: configured -- Live mode available (falls back to Safe mode automatically on any failure)")
        else:
            print("GEMINI_API_KEY: not configured -- Recorded/Replay and Safe mode work with no key; Live mode needs one (see README)")
    except Exception as e:
        print(f"GEMINI_API_KEY: could not check ({e})")

    # Last line, machine-parsed by run.bat/run.sh -- keep this exact format.
    print(f"PORT={port}")


if __name__ == "__main__":
    main()
