import json
import os
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import quote_plus, unquote_plus

from fastapi import FastAPI, Form, HTTPException, Query, Request, Response, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .db import init_db
from .engine import build_response, compile_routes, match_route, parse_config_json
from .repo import check_admin, create_workspace, get_workspace, list_routes, list_workspaces, replace_routes
from .security import new_admin_token, new_user_id


APP_NAME = "MockCloud"

BASE_DIR = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"

app = FastAPI(title=APP_NAME)
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.on_event("startup")
def _startup() -> None:
    init_db()


def _admin_cookie_name(user_id: str) -> str:
    return f"admin_token__{user_id}"


def _get_admin_token_from_cookie(user_id: str, request: Request) -> Optional[str]:
    return request.cookies.get(_admin_cookie_name(user_id))


RECENTS_COOKIE = "recent_workspaces"


def _get_recent_workspace_ids(request: Request) -> list[str]:
    raw = request.cookies.get(RECENTS_COOKIE)
    if not raw:
        return []
    try:
        decoded = unquote_plus(raw)
        data = json.loads(decoded)
        if isinstance(data, list):
            return [x for x in data if isinstance(x, str)][:20]
    except Exception:
        return []
    return []


def _set_recent_workspace_ids(resp: Response, ids: list[str]) -> None:
    resp.set_cookie(
        key=RECENTS_COOKIE,
        value=quote_plus(json.dumps(ids[:20])),
        httponly=False,
        secure=bool(os.environ.get("RAILWAY_ENVIRONMENT")),
        samesite="lax",
        max_age=60 * 60 * 24 * 365,
    )


def _remember_workspace(resp: Response, request: Request, user_id: str) -> None:
    ids = _get_recent_workspace_ids(request)
    ids = [user_id] + [x for x in ids if x != user_id]
    _set_recent_workspace_ids(resp, ids)


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    recent_ids = _get_recent_workspace_ids(request)
    recents = []
    for wid in recent_ids:
        ws = get_workspace(wid)
        if ws:
            recents.append(ws)
    all_workspaces = list_workspaces(limit=50, offset=0)
    return templates.TemplateResponse(
        request=request,
        name="home.html",
        context={"app_name": APP_NAME, "recents": recents, "all_workspaces": all_workspaces},
    )


@app.get("/go")
def go_to_workspace(workspace_id: str = Query(min_length=1, max_length=200)):
    return RedirectResponse(url=f"/w/{workspace_id}", status_code=303)


@app.post("/workspaces")
def create_workspace_action(request: Request, name: str = Form(default="My workspace")):
    user_id = new_user_id()
    admin_token = new_admin_token()
    create_workspace(user_id=user_id, admin_token=admin_token, name=name.strip() or "My workspace")
    resp = RedirectResponse(url=f"/w/{user_id}", status_code=303)
    resp.set_cookie(
        key=_admin_cookie_name(user_id),
        value=admin_token,
        httponly=True,
        secure=bool(os.environ.get("RAILWAY_ENVIRONMENT")),
        samesite="lax",
        max_age=60 * 60 * 24 * 365,
    )
    _remember_workspace(resp, request, user_id)
    return resp


@app.get("/w/{user_id}", response_class=HTMLResponse)
def workspace_page(user_id: str, request: Request):
    ws = get_workspace(user_id)
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")

    token = _get_admin_token_from_cookie(user_id, request)
    is_admin = bool(token) and check_admin(user_id, token)

    routes = list_routes(user_id)
    config_json = "" if not routes else json.dumps(routes, indent=2, ensure_ascii=False)
    mock_base_url = f"{request.base_url}mock/{user_id}".rstrip("/")
    examples = []
    for r in routes[:5]:
        p = r.get("path", "")
        # Fill common placeholders for a copy/paste-friendly example.
        p = p.replace(":id", "123").replace(":name", "rahul").replace(":query", "phone").replace(":include", "posts")
        qs = r.get("query") or {}
        if qs:
            parts = []
            for k, v in qs.items():
                vv = str(v)
                if vv.startswith(":"):
                    vv = vv[1:]
                parts.append(f"{k}={vv}")
            p = f"{p}?{'&'.join(parts)}"
        examples.append(f"{mock_base_url}{p}")
    error = request.query_params.get("error")
    ok = request.query_params.get("ok")
    resp = templates.TemplateResponse(
        request=request,
        name="workspace.html",
        context={
            "app_name": APP_NAME,
            "workspace": ws,
            "is_admin": is_admin,
            "routes": routes,
            "config_json": config_json,
            "mock_base": f"/mock/{user_id}",
            "mock_base_url": mock_base_url,
            "examples": examples,
            "error": error,
            "ok": ok,
        },
    )
    _remember_workspace(resp, request, user_id)
    return resp


@app.post("/w/{user_id}/upload")
async def upload_config(
    user_id: str,
    request: Request,
    config_text: Optional[str] = Form(default=None),
    file: Optional[UploadFile] = None,
):
    ws = get_workspace(user_id)
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")

    token = _get_admin_token_from_cookie(user_id, request)
    if not token or not check_admin(user_id, token):
        raise HTTPException(status_code=401, detail="Admin token missing/invalid for this workspace")

    text: Optional[str] = None
    file_name = getattr(file, "filename", "") if file is not None else ""
    if file is not None and file_name:
        # If a file is selected, it should win over the textarea (which may be prefilled with '[]').
        raw = await file.read()
        text = raw.decode("utf-8", errors="replace")
    else:
        pasted = (config_text or "").strip()
        if pasted:
            text = pasted

    if not text or not text.strip():
        return RedirectResponse(url=f"/w/{user_id}?error=No+config+provided", status_code=303)

    try:
        routes = parse_config_json(text)
    except (ValueError, json.JSONDecodeError) as e:
        msg = f"Invalid config: {e}"
        return RedirectResponse(url=f"/w/{user_id}?error={quote_plus(msg)}", status_code=303)

    replace_routes(user_id, routes)
    return RedirectResponse(url=f"/w/{user_id}?ok=Saved", status_code=303)


@app.get("/api/w/{user_id}/routes")
def api_list_routes(user_id: str):
    ws = get_workspace(user_id)
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return {"user_id": user_id, "routes": list_routes(user_id)}


@app.get("/api/workspaces")
def api_list_workspaces(limit: int = 50, offset: int = 0):
    return {"workspaces": list_workspaces(limit=limit, offset=offset)}


@app.api_route("/mock/{user_id}/{full_path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
def mock_any(user_id: str, full_path: str, request: Request):
    ws = get_workspace(user_id)
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")

    path = "/" + full_path
    raw_routes = list_routes(user_id)
    compiled = compile_routes(raw_routes)
    route, params = match_route(compiled, request.method, path, dict(request.query_params))

    if request.method == "OPTIONS":
        r = Response(status_code=204)
        r.headers["Access-Control-Allow-Origin"] = "*"
        r.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, PATCH, DELETE, OPTIONS"
        r.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
        return r

    if route is None:
        return JSONResponse(
            status_code=404,
            content={"error": f"No mock for {request.method} {path}", "hint": f"Upload routes in /w/{user_id}"},
            headers={"Access-Control-Allow-Origin": "*"},
        )

    status, headers, body = build_response(route, params)
    headers["Access-Control-Allow-Origin"] = "*"
    return JSONResponse(status_code=status, content=body, headers=headers)

