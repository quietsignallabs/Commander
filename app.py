import threading

import uvicorn

from commander.api import create_app
from commander.client_encryption import encrypted_uvicorn_kwargs
from commander.config import Settings
from commander.oauth_listener import start_oauth_listener
from commander.paths import runtime_root


app = create_app()


def run_servers(settings: Settings) -> None:
    start_oauth_listener(app)
    if getattr(settings, "client_encryption_enabled", False):
        threading.Thread(
            target=lambda: uvicorn.run(app, **encrypted_uvicorn_kwargs(settings), reload=False),
            name="CommanderEncryptedClientServer",
            daemon=True,
        ).start()
    uvicorn.run(app, host=settings.host, port=settings.port, reload=False)


if __name__ == "__main__":
    settings = Settings(root_dir=runtime_root())
    app = create_app(settings)
    run_servers(settings)
