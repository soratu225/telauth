"""
tests/test_ws_proxy.py - /ws が Asterisk の WebSocket へ SIP メッセージを双方向に中継すること
"""
import asyncio
import threading

import pytest
import websockets
from starlette.testclient import TestClient

from app.config import get_settings
from app.main import app

settings = get_settings()


class FakeAsteriskWS:
    """受け取ったメッセージに 'ast:' を付けて返し、接続時に 1 通挨拶を送る偽サーバー。"""

    def __init__(self):
        self.port = None
        self.subprotocols = []
        self._loop = asyncio.new_event_loop()
        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    async def _handler(self, ws):
        self.subprotocols.append(ws.subprotocol)
        await ws.send("hello from asterisk")
        async for msg in ws:
            await ws.send("ast:" + msg)

    def _run(self):
        asyncio.set_event_loop(self._loop)

        async def main():
            async with websockets.serve(self._handler, "127.0.0.1", 0, subprotocols=["sip"]) as server:
                self.port = server.sockets[0].getsockname()[1]
                self._ready.set()
                await asyncio.Future()

        self._loop.run_until_complete(main())

    def start(self):
        self._thread.start()
        self._ready.wait(5)


@pytest.fixture
def fake_asterisk(monkeypatch):
    srv = FakeAsteriskWS()
    srv.start()
    monkeypatch.setattr(settings, "asterisk_ws_url", f"ws://127.0.0.1:{srv.port}/ws")
    return srv


def test_ws_proxy_relays_both_directions(fake_asterisk):
    with TestClient(app) as client:
        with client.websocket_connect("/ws", subprotocols=["sip"]) as ws:
            assert ws.receive_text() == "hello from asterisk"
            ws.send_text("REGISTER sip:telauth SIP/2.0")
            assert ws.receive_text() == "ast:REGISTER sip:telauth SIP/2.0"
    assert fake_asterisk.subprotocols == ["sip"]


def test_ws_proxy_closes_when_asterisk_unreachable(monkeypatch):
    monkeypatch.setattr(settings, "asterisk_ws_url", "ws://127.0.0.1:1/ws")
    with TestClient(app) as client:
        with pytest.raises(Exception):
            with client.websocket_connect("/ws", subprotocols=["sip"]) as ws:
                ws.receive_text()
