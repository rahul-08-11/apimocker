import copy
import json
import re
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qsl


def path_to_regex(path: str) -> Tuple[str, List[str]]:
    param_names: List[str] = []

    def replace_param(m: re.Match[str]) -> str:
        param_names.append(m.group(1))
        return r"([^/]+)"

    pattern = re.sub(r":([a-zA-Z_][a-zA-Z0-9_]*)", replace_param, path)
    return f"^{pattern}$", param_names


def resolve_response(value: Any, params: Dict[str, str]) -> Any:
    if isinstance(value, dict):
        return {k: resolve_response(v, params) for k, v in value.items()}
    if isinstance(value, list):
        return [resolve_response(item, params) for item in value]
    if isinstance(value, str) and value.startswith(":"):
        key = value[1:]
        return params.get(key, value)
    return value


@dataclass(frozen=True)
class CompiledRoute:
    method: str
    path: str
    query: Dict[str, Any]
    status: int
    delay_ms: int
    headers: Dict[str, str]
    response: Any
    pattern: re.Pattern[str]
    params: List[str]


def compile_routes(raw_routes: List[Dict[str, Any]]) -> List[CompiledRoute]:
    compiled: List[CompiledRoute] = []
    for r in raw_routes:
        route_path = r["path"]
        inferred_query: Dict[str, Any] = {}
        if "?" in route_path:
            route_path, raw_qs = route_path.split("?", 1)
            inferred_query = {k: v for k, v in parse_qsl(raw_qs, keep_blank_values=True)}
        route_query = dict(r.get("query") or {})
        # Explicit 'query' wins when same key appears in path query-string.
        merged_query = {**inferred_query, **route_query}

        pattern, param_names = path_to_regex(route_path)
        compiled.append(
            CompiledRoute(
                method=r["method"].upper(),
                path=route_path,
                query=merged_query,
                status=int(r.get("status", 200)),
                delay_ms=int(r.get("delay_ms", 0) or 0),
                headers=dict(r.get("headers") or {}),
                response=r.get("response"),
                pattern=re.compile(pattern),
                params=param_names,
            )
        )
    return compiled


def _match_query(
    route_query: Dict[str, Any],
    incoming_query: Dict[str, str],
) -> Tuple[bool, Dict[str, str]]:
    captures: Dict[str, str] = {}
    for key, expected in route_query.items():
        actual = incoming_query.get(key)
        if actual is None:
            return False, {}
        if isinstance(expected, str) and expected.startswith(":"):
            captures[expected[1:]] = actual
            continue
        if str(expected) != actual:
            return False, {}
    return True, captures


def match_route(
    routes: List[CompiledRoute],
    method: str,
    path: str,
    query_params: Optional[Dict[str, str]] = None,
) -> Tuple[Optional[CompiledRoute], Dict[str, str]]:
    method = method.upper()
    query_params = query_params or {}
    best_route: Optional[CompiledRoute] = None
    best_params: Dict[str, str] = {}
    best_score: Optional[Tuple[int, int]] = None

    for r in routes:
        if r.method != method:
            continue
        m = r.pattern.match(path)
        if m:
            params = dict(zip(r.params, m.groups()))
            ok, query_captures = _match_query(r.query, query_params)
            if not ok:
                continue
            params.update(query_captures)
            # Prefer the most specific route:
            # 1) more required query keys
            # 2) fewer path placeholders (more static path)
            score = (len(r.query), -len(r.params))
            if best_score is None or score > best_score:
                best_route = r
                best_params = params
                best_score = score
    return best_route, best_params


def build_response(route: CompiledRoute, params: Dict[str, str]) -> Tuple[int, Dict[str, str], Any]:
    if route.delay_ms:
        time.sleep(route.delay_ms / 1000)
    body = resolve_response(copy.deepcopy(route.response), params)
    headers = dict(route.headers or {})
    if "content-type" not in {k.lower() for k in headers.keys()}:
        headers["Content-Type"] = "application/json"
    return route.status, headers, body


def parse_config_json(config_text: str) -> List[Dict[str, Any]]:
    data = json.loads(config_text)
    if not isinstance(data, list):
        raise ValueError("Config must be a JSON array of routes")
    for i, r in enumerate(data):
        if not isinstance(r, dict):
            raise ValueError(f"Route #{i} must be an object")
        for k in ("method", "path"):
            if k not in r:
                raise ValueError(f"Route #{i} missing required field '{k}'")
        if "status" in r and not isinstance(r["status"], int):
            raise ValueError(f"Route #{i} field 'status' must be an integer")
        if "delay_ms" in r and not isinstance(r["delay_ms"], int):
            raise ValueError(f"Route #{i} field 'delay_ms' must be an integer")
        if "headers" in r and not isinstance(r["headers"], dict):
            raise ValueError(f"Route #{i} field 'headers' must be an object")
        if "query" in r and not isinstance(r["query"], dict):
            raise ValueError(f"Route #{i} field 'query' must be an object")
    return data

