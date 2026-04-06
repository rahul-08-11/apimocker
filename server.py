"""
Local API Mocker
----------------
Spins up a local HTTP server from a JSON config file.

Usage:
    python server.py                        # uses mock.json on port 8000
    python server.py --config mock.json     # explicit config
    python server.py --port 3000            # custom port
"""

import json
import time
import copy
import argparse
import re
from http.server import BaseHTTPRequestHandler, HTTPServer


def load_routes(config_path: str) -> list:
    with open(config_path) as f:
        routes = json.load(f)
    for route in routes:
        pattern, param_names = path_to_regex(route["path"])
        route["_pattern"] = re.compile(pattern)
        route["_params"] = param_names
    return routes


def path_to_regex(path: str):
    """Convert '/users/:id' → regex + ['id']"""
    param_names = []

    def replace_param(m):
        param_names.append(m.group(1))
        return r"([^/]+)"

    pattern = re.sub(r":([a-zA-Z_][a-zA-Z0-9_]*)", replace_param, path)
    return f"^{pattern}$", param_names


def match_route(routes: list, method: str, path: str):
    """Return (route, path_params) or (None, {})."""
    for route in routes:
        if route["method"].upper() != method.upper():
            continue
        m = route["_pattern"].match(path)
        if m:
            params = dict(zip(route["_params"], m.groups()))
            return route, params
    return None, {}


def resolve_response(response, params: dict):
    """Replace ':param' placeholders in response values with actual path param values."""
    if isinstance(response, dict):
        return {k: resolve_response(v, params) for k, v in response.items()}
    if isinstance(response, list):
        return [resolve_response(item, params) for item in response]
    if isinstance(response, str) and response.startswith(":"):
        key = response[1:]
        return params.get(key, response)
    return response


def make_handler(routes: list):
    class MockHandler(BaseHTTPRequestHandler):

        def log_message(self, fmt, *args):
            print(f"  {self.command} {self.path}  →  {fmt % args}")

        def handle_request(self):
            route, params = match_route(routes, self.command, self.path)

            if route is None:
                self._send_json(404, {"error": f"No mock for {self.command} {self.path}"})
                return

            delay = route.get("delay_ms", 0)
            if delay:
                time.sleep(delay / 1000)

            status = route.get("status", 200)
            body = resolve_response(copy.deepcopy(route.get("response")), params)
            self._send_json(status, body)

        def _send_json(self, status: int, body):
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            if body is not None:
                self.wfile.write(json.dumps(body, indent=2).encode())

        def do_OPTIONS(self):
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, PATCH, DELETE, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
            self.end_headers()

        do_GET = handle_request
        do_POST = handle_request
        do_PUT = handle_request
        do_PATCH = handle_request
        do_DELETE = handle_request

    return MockHandler


def main():
    parser = argparse.ArgumentParser(description="Local API Mocker")
    parser.add_argument("--config", default="mock.json", help="Path to mock config (default: mock.json)")
    parser.add_argument("--port", default=8000, type=int, help="Port to listen on (default: 8000)")
    args = parser.parse_args()

    routes = load_routes(args.config)
    handler = make_handler(routes)

    print(f"\n  API Mocker running on http://localhost:{args.port}")
    print(f"  Config: {args.config}  |  {len(routes)} route(s) loaded\n")
    for r in routes:
        delay = f"  [{r['delay_ms']}ms delay]" if r.get("delay_ms") else ""
        print(f"  {r['method']:<7} {r['path']:<30} → {r['status']}{delay}")
    print()

    server = HTTPServer(("", args.port), handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  Stopped.")


if __name__ == "__main__":
    main()