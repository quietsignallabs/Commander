# Commander API Reference

Commander exposes a local HTTP API for creating, editing, managing, and running saved host actions from clients such as Apple Shortcuts, iOS apps, or other LAN tools.

Default base URL:

```text
http://<host-ip>:6767
```

Local-only URL:

```text
http://127.0.0.1:6767
```

## Authentication

API authentication is disabled by default. When enabled in Settings, include this header on every `/api/*` request:

```http
X-Commander-Token: 1234567890
```

Missing or invalid tokens return:

```json
{
  "detail": "Invalid or missing Commander API token"
}
```

with HTTP `401`.

## Data Types

### Action

```json
{
  "id": 1,
  "name": "Run TV Script",
  "type": "ps1",
  "command": null,
  "script_path": "D:\\Code\\Commander\\scripts\\abc-Run-TV-Script.ps1",
  "mode": "wait",
  "timeout_seconds": 30,
  "enabled": true,
  "inputs_enabled": true,
  "input_names": ["message"],
  "created_at": "2026-05-06T18:10:00+00:00",
  "updated_at": "2026-05-06T18:10:00+00:00"
}
```

Action fields:

- `name`: unique action name. Names are case-insensitive for lookup.
- `type`: `cmd`, `powershell`, or `ps1`.
- `command`: command text for `cmd` and `powershell` actions.
- `script_path`: server-local PowerShell script path for `ps1` actions.
- `script_text`: accepted on create/update/edit requests for `ps1` actions, but not returned. Commander saves it under the managed `scripts/` directory.
- `mode`: `wait` or `start`.
- `timeout_seconds`: integer from `1` through `3600`.
- `enabled`: disabled actions are listed but cannot run.
- `inputs_enabled`: allows runtime inputs.
- `input_names`: optional UI/schema hints for runtime inputs.

### Run Result

```json
{
  "id": 42,
  "action_id": 1,
  "action_name": "Run TV Script",
  "status": "completed",
  "started_at": "2026-05-06T18:11:00+00:00",
  "finished_at": "2026-05-06T18:11:01+00:00",
  "exit_code": 0,
  "stdout": "hello\r\n",
  "stderr": "",
  "duration_ms": 120
}
```

Run statuses:

- `running`
- `completed`
- `failed`
- `timeout`

## Actions

### List Actions

```http
GET /api/actions
```

Response: `200`

```json
[
  {
    "id": 1,
    "name": "Echo",
    "type": "cmd",
    "command": "echo hello",
    "script_path": null,
    "mode": "wait",
    "timeout_seconds": 30,
    "enabled": true,
    "inputs_enabled": false,
    "input_names": [],
    "created_at": "2026-05-06T18:10:00+00:00",
    "updated_at": "2026-05-06T18:10:00+00:00"
  }
]
```

### Create Action

```http
POST /api/actions
Content-Type: application/json
```

Create a `cmd` action:

```json
{
  "name": "Echo",
  "type": "cmd",
  "command": "echo hello",
  "mode": "wait",
  "timeout_seconds": 30,
  "enabled": true
}
```

Create a PowerShell command action:

```json
{
  "name": "List Processes",
  "type": "powershell",
  "command": "Get-Process | Select-Object -First 5",
  "mode": "wait"
}
```

Create a managed `.ps1` action from a client:

```json
{
  "name": "Show Current User",
  "type": "ps1",
  "script_text": "Write-Output ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name)",
  "mode": "wait",
  "timeout_seconds": 30
}
```

Response: `201`, action object.

Notes:

- Prefer `script_text` for remote clients. The server writes the script under `scripts/` and returns `script_path`.
- `script_path` is still accepted for server-local administrative clients that already placed a `.ps1` file on the host.
- Duplicate names return `400`.

### Get Action

```http
GET /api/actions/{url-encoded-name}
```

Response: `200`, action object.

Missing actions return `404`.

### Get Action Script

```http
GET /api/actions/{url-encoded-name}/script
```

Use this endpoint before showing a client-side editor for a `ps1` action. It returns the current script file contents so the client can prefill the editor.

Response: `200`

```json
{
  "name": "Show Current User",
  "script_path": "D:\\Code\\Commander\\scripts\\abc-Show-Current-User.ps1",
  "script_text": "Write-Output $env:USERNAME\n"
}
```

Missing actions return `404`. Non-`ps1` actions return `400`.

### Update Action

```http
PUT /api/actions/{url-encoded-name}
Content-Type: application/json
```

Request body uses the same shape as create.

Update an existing managed script:

```json
{
  "name": "Show Current User",
  "type": "ps1",
  "script_text": "Write-Output $env:USERNAME",
  "mode": "wait",
  "timeout_seconds": 45,
  "enabled": true
}
```

For existing `ps1` actions, omitting both `script_text` and `script_path` preserves the current script file.

Response: `200`, updated action object.

Missing actions return `404`.

### Edit Action

```http
PATCH /api/actions/{url-encoded-name}
Content-Type: application/json
```

Use this endpoint when a client wants to change only some fields. Omitted fields keep their current values.

Edit command text and disable an action:

```json
{
  "command": "echo edited",
  "enabled": false
}
```

Rename an action:

```json
{
  "name": "Edited Action Name"
}
```

Edit a managed `.ps1` script without resending every action field:

```json
{
  "script_text": "Write-Output $env:USERNAME",
  "timeout_seconds": 60
}
```

Response: `200`, edited action object.

Missing actions return `404`. Invalid edits return `400`.

Client-side script edit flow:

1. Call `GET /api/actions/{name}/script`.
2. Load `script_text` into the client editor.
3. Submit the edited text with `PATCH /api/actions/{name}` and a `script_text` field.

### Delete Action

```http
DELETE /api/actions/{url-encoded-name}
```

Response: `204` with no body.

## Run Actions

### Run Saved Action

```http
POST /api/actions/{url-encoded-name}/run
Content-Type: application/json
```

For actions without inputs, send no body or `{}`.

For input-enabled actions, prefer wrapped inputs:

```json
{
  "inputs": {
    "message": "hello"
  }
}
```

Direct input JSON is also accepted:

```json
{
  "message": "hello"
}
```

Inputs are exposed to commands as environment variables:

```powershell
$env:COMMANDER_INPUT_MESSAGE
```

Uploaded and managed `.ps1` actions also receive matching PowerShell parameters:

```powershell
param(
  [string]$message
)

Write-Output $message
```

Response for `wait` mode:

```json
{
  "id": 42,
  "action_id": 1,
  "action_name": "Echo",
  "status": "completed",
  "started_at": "2026-05-06T18:11:00+00:00",
  "finished_at": "2026-05-06T18:11:01+00:00",
  "exit_code": 0,
  "stdout": "hello\r\n",
  "stderr": "",
  "duration_ms": 120
}
```

Response for `start` mode:

```json
{
  "id": 43,
  "action_id": 1,
  "action_name": "Background Task",
  "status": "running",
  "started_at": "2026-05-06T18:11:00+00:00",
  "finished_at": null,
  "exit_code": null,
  "stdout": "",
  "stderr": "",
  "duration_ms": null
}
```

Disabled actions return `400`.

## AI Actions

AI endpoints require ChatGPT to be connected in Commander Settings. They use the selected model and the same script-generation rules as the web UI.

### Generate AI Draft

```http
POST /api/ai/actions/draft
Content-Type: application/json
```

Request:

```json
{
  "description": "Create an action that prints the current Windows user"
}
```

Response: `200`

```json
{
  "name": "Show Current User",
  "script": "Write-Output ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name)\n",
  "explanation": "Shows the Windows account running Commander.",
  "timeout_seconds": 30,
  "inputs_enabled": false,
  "input_names": []
}
```

This endpoint does not save an action. Use it when a client wants to show a review screen before creation.

### Generate And Create AI Action

```http
POST /api/ai/actions
Content-Type: application/json
```

Request:

```json
{
  "description": "Create an action that accepts a message input and prints it"
}
```

Response: `201`, saved action object:

```json
{
  "id": 2,
  "name": "Say Message",
  "type": "ps1",
  "command": null,
  "script_path": "D:\\Code\\Commander\\scripts\\def-Say-Message.ps1",
  "mode": "wait",
  "timeout_seconds": 30,
  "enabled": true,
  "inputs_enabled": true,
  "input_names": ["message"],
  "created_at": "2026-05-06T18:12:00+00:00",
  "updated_at": "2026-05-06T18:12:00+00:00"
}
```

Generation, validation, duplicate-name, or ChatGPT connection failures return `400` with a `detail` message.

## Runs

### List Runs

```http
GET /api/runs
```

Response: `200`

```json
[
  {
    "id": 42,
    "action_id": 1,
    "action_name": "Echo",
    "status": "completed",
    "started_at": "2026-05-06T18:11:00+00:00",
    "finished_at": "2026-05-06T18:11:01+00:00",
    "exit_code": 0,
    "stdout": "hello\r\n",
    "stderr": "",
    "duration_ms": 120
  }
]
```

The server returns the latest 100 run records.

## URL Encoding

Action names are path segments and must be percent-encoded.

```text
Run TV Script -> Run%20TV%20Script
```

PowerShell example:

```powershell
$encoded = [System.Uri]::EscapeDataString("Run TV Script")
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:6767/api/actions/$encoded/run" -Headers @{"X-Commander-Token" = "1234567890"}
```

## cURL Examples

Create a managed `.ps1` action:

```powershell
curl.exe -X POST "http://127.0.0.1:6767/api/actions" `
  -H "X-Commander-Token: 1234567890" `
  -H "Content-Type: application/json" `
  -d "{\"name\":\"Show User\",\"type\":\"ps1\",\"script_text\":\"Write-Output `$env:USERNAME\"}"
```

Run it:

```powershell
curl.exe -X POST "http://127.0.0.1:6767/api/actions/Show%20User/run" `
  -H "X-Commander-Token: 1234567890"
```

Generate an AI draft:

```powershell
curl.exe -X POST "http://127.0.0.1:6767/api/ai/actions/draft" `
  -H "X-Commander-Token: 1234567890" `
  -H "Content-Type: application/json" `
  -d "{\"description\":\"Create an action that shows the current user\"}"
```

List actions with auth:

```powershell
curl.exe -X GET "http://127.0.0.1:6767/api/actions" `
  -H "X-Commander-Token: 1234567890"
```

## HTTP Status Codes

- `200`: request succeeded.
- `201`: action created.
- `204`: action deleted.
- `400`: validation, disabled action, duplicate action, AI generation, or ChatGPT connection error.
- `401`: missing or invalid `X-Commander-Token`.
- `404`: action not found.
- `422`: malformed request body or missing required JSON field.

## Client Notes

- Treat action names as user-facing identifiers and URL-encode them when used in paths.
- Prefer `script_text` over `script_path` when creating `ps1` actions from a client.
- Call `GET /api/actions/{name}/script` before editing a `ps1` action so the client can load the current script contents.
- Use `PATCH /api/actions/{name}` for partial edits and `PUT /api/actions/{name}` for full replacement.
- Store API tokens in the platform secure store.
- Consider showing AI drafts to users before saving, especially for actions that run host commands.
- Use longer client request timeouts for `wait` actions. A practical timeout is `timeout_seconds + 5`.
