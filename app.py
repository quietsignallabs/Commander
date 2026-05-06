import uvicorn

from commander.api import create_app
from commander.config import Settings
from commander.oauth_listener import start_oauth_listener
from commander.paths import runtime_root


app = create_app()


def run_servers(settings: Settings) -> None:
    start_oauth_listener(app)
    uvicorn.run(app, host=settings.host, port=settings.port, reload=False)


if __name__ == "__main__":
    settings = Settings(root_dir=runtime_root())
    settings.ensure_directories()
    run_servers(settings)
