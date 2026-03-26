"""HTTP server for packaged demo pages (pipx-friendly).

Run as: python -m browser_agent.demos.http_server [--port PORT] [--host HOST]
"""

from __future__ import annotations

import argparse
import os
import socket
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

from browser_agent.demos import demo_pages_dir


class CORSRequestHandler(SimpleHTTPRequestHandler):
    """HTTP request handler with CORS headers for local development."""

    def end_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        super().end_headers()

    def log_message(self, format: str, *args) -> None:
        print(f"[{self.log_date_time_string()}] {self.address_string()} - {format % args}")


def get_local_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0)
        try:
            s.connect(("10.254.254.254", 1))
            ip = s.getsockname()[0]
        except Exception:
            ip = "127.0.0.1"
        finally:
            s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def main() -> int:
    parser = argparse.ArgumentParser(description="Browser Agent demo pages HTTP server")
    parser.add_argument("--port", type=int, default=8765, help="Port (default: 8765)")
    parser.add_argument(
        "--host",
        type=str,
        default="127.0.0.1",
        help="Host to bind (default: 127.0.0.1)",
    )
    args = parser.parse_args()

    pages_dir = demo_pages_dir()
    if not pages_dir.is_dir():
        print(f"Error: Pages directory not found at {pages_dir}")
        return 1

    os.chdir(pages_dir)
    server = HTTPServer((args.host, args.port), CORSRequestHandler)

    local_ip = get_local_ip()
    print("=" * 60)
    print("  Browser Agent Demo Server")
    print("=" * 60)
    print()
    print("Server running on:")
    print(f"  http://localhost:{args.port}/")
    print(f"  http://{local_ip}:{args.port}/")
    print()
    print("Available demo pages:")
    print(f"  http://localhost:{args.port}/inbox_demo.html")
    print(f"  http://localhost:{args.port}/food_demo.html")
    print(f"  http://localhost:{args.port}/jobs_demo.html")
    print()
    print("Press Ctrl+C to stop")
    print("=" * 60)
    print()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n\nShutting down server...")
        server.shutdown()
        print("Server stopped.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
