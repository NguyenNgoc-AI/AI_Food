import os
import socket
import tempfile
import threading
import time
import unittest
from pathlib import Path

import uvicorn

from backend.main import app


class LiveServer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(tmp.cleanup)
        previous = os.environ.get("SMARTFOOD_DB")
        os.environ["SMARTFOOD_DB"] = str(Path(tmp.name) / "g1.sqlite3")
        def restore():
            if previous is None:
                os.environ.pop("SMARTFOOD_DB", None)
            else:
                os.environ["SMARTFOOD_DB"] = previous
        cls.addClassCleanup(restore)
        port = socket.socket()
        port.bind(("127.0.0.1", 0))
        cls.url = f"http://127.0.0.1:{port.getsockname()[1]}"
        cls.server = uvicorn.Server(uvicorn.Config(app, log_level="warning", ws="none"))
        thread = threading.Thread(target=cls.server.run, kwargs={"sockets":[port]}, daemon=True)
        thread.start()
        def stop():
            cls.server.should_exit = True
            thread.join(8)
            port.close()
        cls.addClassCleanup(stop)
        for _ in range(200):
            if cls.server.started:
                return
            if not thread.is_alive():
                break
            time.sleep(.05)
        raise RuntimeError("Test server did not start")
