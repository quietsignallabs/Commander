from __future__ import annotations

import threading
import webbrowser
import logging
import socket
from pathlib import Path

import pystray
import uvicorn
from PIL import Image

from commander.api import create_app
from commander.config import Settings
from commander.oauth_listener import start_oauth_listener
from commander.paths import resource_path, runtime_root


LOCALHOST = "127.0.0.1"


class CommanderTray:
    def __init__(self) -> None:
        self.settings = Settings(root_dir=runtime_root())
        self.settings.ensure_directories()
        configure_logging(self.settings.root_dir)
        logging.info("Starting Commander tray from %s", self.settings.root_dir)
        self.app = create_app(self.settings)
        self.server = uvicorn.Server(
            uvicorn.Config(
                self.app,
                host=self.settings.host,
                port=self.settings.port,
                log_level="warning",
                log_config=None,
                access_log=False,
            )
        )
        self.server_thread = threading.Thread(target=self.run_server, name="CommanderServer", daemon=True)
        self.icon = pystray.Icon(
            "Commander",
            load_tray_image(),
            "Commander",
            pystray.Menu(
                pystray.MenuItem("Open Commander", self.open_config, default=True),
                pystray.MenuItem("Quit", self.quit),
            ),
        )

    def run(self) -> None:
        logging.info("Starting OAuth listener")
        start_oauth_listener(self.app)
        logging.info("Starting Commander server thread")
        self.server_thread.start()
        logging.info("Starting tray icon")
        self.icon.run()

    def run_server(self) -> None:
        try:
            self.server.run()
        except Exception:
            logging.exception("Commander server crashed")
            raise

    def open_config(self, _icon=None, _item=None) -> None:
        url = commander_url(self.settings.port)
        logging.info("Opening Commander web portal at %s", url)
        webbrowser.open(url)

    def quit(self, _icon=None, _item=None) -> None:
        logging.info("Quitting Commander")
        self.server.should_exit = True
        self.icon.stop()


def load_tray_image() -> Image.Image:
    icon_path = resource_path("assets/commander.ico")
    if icon_path.exists():
        return Image.open(icon_path)
    return Image.new("RGBA", (64, 64), "#305096")


def commander_url(port: int) -> str:
    return f"http://{lan_ip_address()}:{port}"


def lan_ip_address() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("8.8.8.8", 80))
            address = probe.getsockname()[0]
    except OSError:
        logging.exception("Unable to detect LAN IP address")
        return LOCALHOST

    if address.startswith("127."):
        return LOCALHOST
    return address


def configure_logging(root_dir: Path) -> None:
    logging.basicConfig(
        filename=root_dir / "commander.tray.log",
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(threadName)s %(message)s",
        force=True,
    )


def main() -> None:
    root_dir = runtime_root()
    configure_logging(root_dir)
    try:
        CommanderTray().run()
    except Exception:
        logging.exception("Commander tray failed during startup")
        raise


if __name__ == "__main__":
    main()
