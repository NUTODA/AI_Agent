"""Simple HTTP server for demo pages.

Usage:
    python server.py [--port PORT]

The server will serve the demo pages from the pages/ directory
and print the URLs to access them.
"""

from __future__ import annotations

import argparse
import os
import socket
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path


class CORSRequestHandler(SimpleHTTPRequestHandler):
    """HTTP request handler with CORS headers for local development."""

    def end_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        super().end_headers()

    def log_message(self, format: str, *args) -> None:
        """Override to provide cleaner log output."""
        print(f"[{self.log_date_time_string()}] {self.address_string()} - {format % args}")


def get_local_ip() -> str:
    """Get the local IP address for displaying server URLs."""
    try:
        # Connect to a dummy address to get the local IP
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0)
        try:
            s.connect(('10.254.254.254', 1))
            ip = s.getsockname()[0]
        except Exception:
            ip = '127.0.0.1'
        finally:
            s.close()
        return ip
    except Exception:
        return '127.0.0.1'


def main() -> int:
    """Run the demo server."""
    parser = argparse.ArgumentParser(description="Demo pages HTTP server")
    parser.add_argument(
        "--port",
        type=int,
        default=8765,
        help="Port to run the server on (default: 8765)",
    )
    parser.add_argument(
        "--host",
        type=str,
        default="0.0.0.0",
        help="Host to bind to (default: 0.0.0.0)",
    )
    args = parser.parse_args()

    # Change to the pages directory to serve files
    pages_dir = Path(__file__).parent / "pages"
    if not pages_dir.exists():
        print(f"Error: Pages directory not found at {pages_dir}")
        return 1

    os.chdir(pages_dir)

    server = HTTPServer((args.host, args.port), CORSRequestHandler)

    local_ip = get_local_ip()

    print("=" * 60)
    print("  Browser Agent Demo Server")
    print("=" * 60)
    print()
    print(f"Server running on:")
    print(f"  http://localhost:{args.port}/")
    print(f"  http://{local_ip}:{args.port}/")
    print()
    print("Available demo pages:")
    print(f"  http://localhost:{args.port}/inbox_demo.html")
    print(f"  http://localhost:{args.port}/food_demo.html")
    print(f"  http://localhost:{args.port}/jobs_demo.html")
    print()
    print("Press Ctrl+C to stop the server")
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
    exit(main())
