# MockCloud

MockCloud is a self-hosted mock API platform for internal use.  

![Demo Video](https://vumbnail.com/1180453469.jpg)](https://github.com/user-attachments/assets/64bea6dd-8714-4e2a-8c98-0640e853f9b0)

Users upload route configs from the UI and consume endpoints under:

`/mock/<workspace-id>/...`

Example:

`https://your-domain.com/mock/AbCdEf/users/42`

## 1) Run on your machine

### Requirements

- Docker

### Start

```bash
docker build -t mockcloud .
docker run --rm -p 8000:8000 --name mockcloud mockcloud
```

### Keep your workspaces (important)

Workspaces and configs are stored in SQLite. If the container is restarted without a volume, the SQLite file is lost and workspace IDs/configs disappear.

Run with a Docker volume:

```bash
docker run --rm -p 8000:8000 --name mockcloud \
  -e MOCKER_DB_PATH=/data/mocker.sqlite3 \
  -v mockcloud_data:/data \
  mockcloud
```

Open:

`http://127.0.0.1:8000`

## 2) Use from UI

1. Open Home and create a workspace.
2. Open the workspace page (`/w/<workspace-id>`).
3. Upload a JSON file or paste JSON in the textarea.
4. Click `Save routes`.
5. Call the generated mock URLs shown in the workspace page.

Notes:

- If a file is selected, file content is used.
- If no file is selected, pasted textarea JSON is used.
- Routes are replaced on every save for that workspace.
- Home shows “Recent workspaces” for that browser.

## 3) Route config format

Upload a JSON array.

```json
[
  { "method": "GET", "path": "/users", "response": [{ "id": 1, "name": "Alice" }] },
  { "method": "GET", "path": "/users/:id", "response": { "id": ":id" } },
  { "method": "GET", "path": "/users", "query": { "name": ":name" }, "response": { "name": ":name" } },
  { "method": "GET", "path": "/status", "response": { "status": "ok" } }
]
```

Supported fields:

| Field | Required | Description |
|---|---|---|
| `method` | yes | HTTP method (`GET`, `POST`, `PUT`, `PATCH`, `DELETE`) |
| `path` | yes | Route path, supports params like `:id` |
| `query` | no | Query matcher, example `{ "name": ":name" }` |
| `status` | no | HTTP status code (default `200`) |
| `delay_ms` | no | Delay before response in milliseconds |
| `headers` | no | Extra response headers object |
| `response` | no | JSON response body |

Matching behavior:

- `/users` matches `path: "/users"`
- `/users/21` matches `path: "/users/:id"` and binds `id=21`
- `/users?name=rahul` matches `path: "/users"` + `query: {"name": ":name"}`

## 4) Internal usage pattern

- Keep one workspace per team/service/environment.
- Share only the mock base URL with consumers.
- Update route configs through the workspace UI when behavior changes.
