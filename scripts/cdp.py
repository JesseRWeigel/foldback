#!/usr/bin/env python3
"""A small Chrome DevTools Protocol client, with no third-party dependencies.

Why not ``chrome --headless --screenshot --window-size=...``: it does not set the viewport.
Measured on the machine this was written on, ``--window-size=390,844`` with ``--dump-dom``
reports ``document.documentElement.clientWidth === 500``. Any narrow-viewport check built on
that flag is measuring a viewport nobody asked for. ``Emulation.setDeviceMetricsOverride``
sets the real thing, and the checks assert the width they got.

Why not Playwright: the shared browser instance in this workspace gets navigated out from
under a running check by other agents. This launches its own Chrome with its own profile
directory, and every evaluation asserts the page identity anyway.
"""

from __future__ import annotations

import base64
import json
import os
import shutil
import socket
import struct
import subprocess
import tempfile
import time
import urllib.request

CHROME_CANDIDATES = [
    "google-chrome", "google-chrome-stable", "chromium", "chromium-browser",
]

# Flags that must never appear. Both of them put Chrome into an endless crash-restart loop on
# this machine, which shows up as a check that hangs rather than one that fails.
FORBIDDEN_FLAGS = ("--disable-crashpad-for-testing", "--disable-features=Crashpad")


class ChromeMissing(RuntimeError):
    pass


def find_chrome() -> str:
    for name in CHROME_CANDIDATES:
        path = shutil.which(name)
        if path:
            return path
    raise ChromeMissing(
        "no Chrome or Chromium binary found on PATH (looked for "
        + ", ".join(CHROME_CANDIDATES)
        + "). Install one with: apt-get install chromium-browser"
    )


class WebSocket:
    """Just enough RFC 6455 to talk to Chrome: text frames, masking, ping replies."""

    def __init__(self, url: str, timeout: float = 30.0):
        if not url.startswith("ws://"):
            raise ValueError(f"expected a ws:// url, got {url!r}")
        hostport, _, path = url[5:].partition("/")
        host, _, port = hostport.partition(":")
        self.sock = socket.create_connection((host, int(port)), timeout=timeout)
        key = base64.b64encode(os.urandom(16)).decode()
        self.sock.sendall(
            (
                f"GET /{path} HTTP/1.1\r\nHost: {hostport}\r\nUpgrade: websocket\r\n"
                f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\n"
                f"Sec-WebSocket-Version: 13\r\n\r\n"
            ).encode()
        )
        buf = b""
        while b"\r\n\r\n" not in buf:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise RuntimeError("chrome closed the websocket during the handshake")
            buf += chunk
        if b" 101 " not in buf.split(b"\r\n")[0]:
            raise RuntimeError(f"websocket handshake refused: {buf[:200]!r}")
        self.buf = buf.split(b"\r\n\r\n", 1)[1]

    def _read(self, count: int) -> bytes:
        while len(self.buf) < count:
            chunk = self.sock.recv(1 << 16)
            if not chunk:
                raise RuntimeError("chrome closed the websocket")
            self.buf += chunk
        out, self.buf = self.buf[:count], self.buf[count:]
        return out

    def send(self, obj) -> None:
        payload = json.dumps(obj).encode()
        size = len(payload)
        header = b"\x81"
        if size < 126:
            header += struct.pack("!B", 0x80 | size)
        elif size < 1 << 16:
            header += struct.pack("!BH", 0x80 | 126, size)
        else:
            header += struct.pack("!BQ", 0x80 | 127, size)
        mask = os.urandom(4)
        self.sock.sendall(
            header + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        )

    def recv(self):
        while True:
            first, second = self._read(2)
            opcode = first & 0x0F
            size = second & 0x7F
            if size == 126:
                size = struct.unpack("!H", self._read(2))[0]
            elif size == 127:
                size = struct.unpack("!Q", self._read(8))[0]
            data = self._read(size) if size else b""
            if opcode == 0x8:
                raise RuntimeError("chrome closed the websocket")
            if opcode == 0x9:  # ping, answer with pong
                self.sock.sendall(
                    b"\x8a" + struct.pack("!B", 0x80 | len(data)) + os.urandom(4) + data
                )
                continue
            if opcode in (0x1, 0x2):
                return json.loads(data.decode())

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass


class Chrome:
    def __init__(self, binary: str | None = None, launch_timeout: float = 60.0):
        self.binary = binary or find_chrome()
        self.profile = tempfile.mkdtemp(prefix="foldback-chrome-")
        argv = [
            self.binary,
            "--headless=new",
            "--no-sandbox",
            "--disable-gpu",
            "--hide-scrollbars",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-extensions",
            "--remote-debugging-port=0",
            f"--user-data-dir={self.profile}",
            "about:blank",
        ]
        for flag in argv:
            if flag in FORBIDDEN_FLAGS:
                raise AssertionError(f"{flag} is banned: it hangs Chrome on this machine")
        self.proc = subprocess.Popen(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        port_file = os.path.join(self.profile, "DevToolsActivePort")
        deadline = time.time() + launch_timeout
        port = None
        while time.time() < deadline:
            if self.proc.poll() is not None:
                raise RuntimeError(f"chrome exited immediately with {self.proc.returncode}")
            if os.path.exists(port_file):
                lines = open(port_file, encoding="utf-8").read().split("\n")
                if len(lines) >= 2 and lines[0].strip():
                    port = int(lines[0].strip())
                    break
            time.sleep(0.05)
        if port is None:
            self.close()
            raise RuntimeError(f"chrome never wrote a debugging port to {port_file}")

        targets = json.loads(
            urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=30).read()
        )
        pages = [t for t in targets if t.get("type") == "page" and t.get("webSocketDebuggerUrl")]
        if not pages:
            self.close()
            raise RuntimeError("chrome exposed no page target to attach to")
        self.ws = WebSocket(pages[0]["webSocketDebuggerUrl"])
        self.next_id = 0
        self.events: list[dict] = []

    def call(self, method: str, **params):
        self.next_id += 1
        message_id = self.next_id
        self.ws.send({"id": message_id, "method": method, "params": params})
        while True:
            message = self.ws.recv()
            if message.get("id") == message_id:
                if "error" in message:
                    raise RuntimeError(f"{method} failed: {message['error']}")
                return message.get("result", {})
            if "method" in message:
                self.events.append(message)

    def drain(self) -> list[dict]:
        """Collected protocol events. Console errors arrive here."""
        return list(self.events)

    def evaluate(self, expression: str, expect_title: str | None = None):
        """Run JavaScript and return the value. Asserts page identity in the same round trip.

        Another agent cannot navigate this browser, since it is a private instance, but the
        identity assertion also catches the more likely failure: navigating to the wrong file,
        or measuring before the page finished replacing itself.
        """
        if expect_title is not None:
            wrapped = (
                "(function(){ if (document.title.indexOf(" + json.dumps(expect_title) +
                ") < 0) { throw new Error('wrong page: ' + document.title); } return ("
                + expression + "); })()"
            )
        else:
            wrapped = "(function(){ return (" + expression + "); })()"
        result = self.call("Runtime.evaluate", expression=wrapped, returnByValue=True,
                           awaitPromise=True)
        if "exceptionDetails" in result:
            details = result["exceptionDetails"]
            text = details.get("exception", {}).get("description") or details.get("text")
            raise RuntimeError(f"page threw: {text}")
        return result["result"].get("value")

    def viewport(self, width: int, height: int) -> None:
        self.call("Emulation.setDeviceMetricsOverride", width=width, height=height,
                  deviceScaleFactor=1, mobile=False)

    def emulate_color_scheme(self, value: str) -> None:
        """``light``, ``dark`` or ``""`` to clear the override."""
        features = [{"name": "prefers-color-scheme", "value": value}] if value else []
        self.call("Emulation.setEmulatedMedia", features=features)

    def navigate(self, url: str) -> None:
        self.call("Page.navigate", url=url)

    def wait_for(self, expression: str, timeout: float = 30.0, poll: float = 0.1):
        deadline = time.time() + timeout
        last = None
        while time.time() < deadline:
            try:
                last = self.evaluate(expression)
            except RuntimeError as exc:
                last = f"threw: {exc}"
            if last:
                return last
            time.sleep(poll)
        raise TimeoutError(f"condition never became true: {expression} (last value {last!r})")

    def close(self) -> None:
        try:
            self.ws.close()
        except Exception:
            pass
        try:
            self.proc.terminate()
            self.proc.wait(timeout=10)
        except Exception:
            try:
                self.proc.kill()
            except Exception:
                pass
        shutil.rmtree(self.profile, ignore_errors=True)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False
