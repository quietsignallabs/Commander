# Commander

Commander is a local Windows automation server for saving named actions and running them from a browser, an iPhone client, curl, or any HTTP client on your local network.

It is intended for personal and LAN automation. You create trusted actions on the Windows host, then trigger those actions by name from other devices or client apps. Actions can run command prompt commands, PowerShell commands, or managed `.ps1` scripts.

## What Commander Does

Commander provides:

- A local web UI for creating, editing, running, and deleting saved actions.
- A JSON API for external clients.
- Managed PowerShell script storage for `.ps1` actions.
- Runtime inputs that clients can pass when an action runs.
- Run history with stdout, stderr, exit code, status, and duration.
- API token authentication.
- AI-assisted PowerShell action generation when ChatGPT is connected in Settings.
- A Windows tray executable built with PyInstaller.

Common uses:

- Trigger a Windows script from an iPhone app.
- Run a saved PowerShell action from Apple Shortcuts.
- Start a local media or utility workflow from another device.
- Build a custom client that lists, edits, and runs saved host actions.

## Supported Action Types

### `cmd`

Runs through:

```text
cmd.exe /c
```

Example command:

```cmd
echo hello
```

### `powershell`

Runs a PowerShell command with non-interactive settings.

Example command:

```powershell
Get-Process | Select-Object -First 5
```

### `ps1`

Runs a managed PowerShell script. Scripts are stored under the runtime `scripts` folder. API clients can create and edit these actions by sending `script_text`; they do not need filesystem access to the Windows host.

## Run Modes

### `wait`

Commander waits for the action to finish and returns:

- Run ID
- Status
- Exit code
- stdout
- stderr
- Duration

### `start`

Commander starts the action and immediately returns a running result. Use this for long-running background actions.

## Requirements

- Windows 10 or newer
- Python 3.11 or newer
- PowerShell
- Network access between the client device and the Windows host when using Commander from another device

## Install From Source

From the project folder:

```powershell
python -m pip install -r requirements.txt
```

If you prefer a virtual environment:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

## Run From Source

```powershell
python app.py
```

Open the web UI on the Windows host:

```text
http://127.0.0.1:6767
```

Open it from another device on the same network:

```text
http://<host-ip>:6767
```

Example:

```text
http://192.168.1.50:6767
```

## First-Time Setup

1. Start Commander with `python app.py`.
2. Open `http://127.0.0.1:6767`.
3. Create an action from the web UI.
4. Run the action from the web UI to confirm it works.
5. From a client device, call the API using the Windows host IP address.
6. If you expose Commander beyond a trusted local machine, enable API authentication in Settings.

## Runtime Inputs

Actions can accept runtime inputs from API clients. Inputs are sent as JSON:

```json
{
  "inputs": {
    "message": "hello"
  }
}
```

Commander exposes each input as an environment variable:

```powershell
$env:COMMANDER_INPUT_MESSAGE
```

For `.ps1` actions, Commander also passes matching PowerShell parameters:

```powershell
param(
  [string]$message
)

Write-Output $message
```

## Basic API Use

The default local API base URL is:

```text
http://127.0.0.1:6767
```

From another device, replace `127.0.0.1` with the Windows host IP address.

The examples below assume API authentication is enabled and use this fake token:

```text
1234567890
```

### List Actions

```powershell
curl.exe "http://127.0.0.1:6767/api/actions" -H "X-Commander-Token: 1234567890"
```

### Create A Managed PowerShell Script Action

PowerShell quoting is easiest when the JSON body is stored in a variable:

```powershell
$body = @{
  name = "Show User"
  type = "ps1"
  script_text = "Write-Output `$env:USERNAME"
} | ConvertTo-Json

curl.exe -X POST "http://127.0.0.1:6767/api/actions" -H "X-Commander-Token: 1234567890" -H "Content-Type: application/json" -d $body
```

### Load A Script For Client-Side Editing

Use this before showing a `.ps1` editor in a client:

```powershell
curl.exe "http://127.0.0.1:6767/api/actions/Show%20User/script" -H "X-Commander-Token: 1234567890"
```

Response shape:

```json
{
  "name": "Show User",
  "script_path": "D:\\Path\\To\\scripts\\abc-Show-User.ps1",
  "script_text": "Write-Output $env:USERNAME\n"
}
```

### Partially Edit An Action

```powershell
$body = @{
  script_text = "Write-Output 'edited'"
} | ConvertTo-Json

curl.exe -X PATCH "http://127.0.0.1:6767/api/actions/Show%20User" -H "X-Commander-Token: 1234567890" -H "Content-Type: application/json" -d $body
```

Use `PATCH` when changing only some fields. Use `PUT` when replacing the full action definition.

### Run An Action

```powershell
curl.exe -X POST "http://127.0.0.1:6767/api/actions/Show%20User/run" -H "X-Commander-Token: 1234567890"
```

### Run An Action With Inputs

```powershell
$body = @{
  inputs = @{
    message = "hello from client"
  }
} | ConvertTo-Json

curl.exe -X POST "http://127.0.0.1:6767/api/actions/Say%20Message/run" -H "X-Commander-Token: 1234567890" -H "Content-Type: application/json" -d $body
```

### Generate An AI Action Draft

ChatGPT must be connected in Commander Settings first.

```powershell
$body = @{
  description = "Create an action that prints the current Windows user"
} | ConvertTo-Json

curl.exe -X POST "http://127.0.0.1:6767/api/ai/actions/draft" -H "X-Commander-Token: 1234567890" -H "Content-Type: application/json" -d $body
```

### Generate And Save An AI Action

```powershell
$body = @{
  description = "Create an action that accepts a message input and prints it"
} | ConvertTo-Json

curl.exe -X POST "http://127.0.0.1:6767/api/ai/actions" -H "X-Commander-Token: 1234567890" -H "Content-Type: application/json" -d $body
```

See `docs/api.md` for the full API reference.

## Authentication

Authentication is disabled by default. Enable it from the Settings page to require an API token for `/api/*` requests.

When authentication is enabled, include:

```http
X-Commander-Token: 1234567890
```

PowerShell example:

```powershell
curl.exe "http://127.0.0.1:6767/api/actions" -H "X-Commander-Token: 1234567890"
```

Security notes:

- Use Commander only on trusted local networks unless you add your own secure reverse proxy and access controls.
- Do not commit runtime settings, local databases, generated scripts, tokens, logs, or `.env` files.
- Review generated AI scripts before running them.
- Avoid creating actions that expose secrets, browser data, SSH keys, or private files.

## Project Layout

```text
app.py                  FastAPI entry point for running from source
launcher.py             Windows tray launcher entry point
commander/              Application source code
templates/              Web UI templates
static/                 Web UI CSS and JavaScript
assets/                 Application icon and packaged assets
docs/api.md             Full API reference
requirements.txt        Python dependencies
commander.spec          PyInstaller build specification
```

Runtime folders are created when Commander runs and are intentionally not included in this release package:

```text
data/
scripts/
dist/
build/
```

## Compile To EXE

Install dependencies first:

```powershell
python -m pip install -r requirements.txt
```

Build the Windows tray executable:

```powershell
python -m PyInstaller commander.spec --clean --noconfirm
```

The compiled app is written to:

```text
dist\Commander.exe
```

When the EXE runs, it creates runtime folders and files beside `Commander.exe`, including:

```text
data\
scripts\
commander.tray.log
```

Do not commit those runtime files.

## Troubleshooting

### The web UI does not open

Confirm the server is running and check:

```text
http://127.0.0.1:6767
```

If the port is already in use, stop the other process or change the configured port in the application settings.

### Another device cannot connect

Check:

- The Windows host and client are on the same network.
- You are using the Windows host LAN IP address, not `127.0.0.1`.
- Windows Firewall allows inbound connections to the Commander port.
- The server is listening on the expected port.

### API returns `401`

Authentication is enabled. Add the `X-Commander-Token` header with the token from Settings.

### API returns `404`

The action name may be wrong or not URL-encoded. Spaces should be encoded as `%20`.

### PowerShell script edits do not show in the client

Call:

```text
GET /api/actions/{name}/script
```

Use the returned `script_text` to populate the editor, then send edited text with:

```text
PATCH /api/actions/{name}
```
