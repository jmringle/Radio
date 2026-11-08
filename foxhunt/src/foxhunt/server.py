"""The local web server: a background loop reads the source about 10 times a second and pushes
each reading to the page over a WebSocket. Listens on 127.0.0.1 only (README threat model)."""
import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from foxhunt.dsp import SAMPLE_RATE, measure
from foxhunt.meter import Meter, parse_settings
from foxhunt.sources import SourceError

STATIC = Path(__file__).parent / "static"
READ_SAMPLES = SAMPLE_RATE // 10  # 0.1 s per reading
UNEXPECTED = "Unexpected error reading the signal; retrying. Details are in the terminal."
# T2: scripts only from this server, no framing. connect-src 'self' covers the WebSocket.
HEADERS = {
    "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; "
                               "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
}
log = logging.getLogger("foxhunt")


def create_app(source, meter: Meter, port: int, retry_s: float = 2.0) -> FastAPI:
    hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
    origins = {f"http://{host}" for host in hosts}
    clients: set[WebSocket] = set()
    state = {"error": None, "gain": None, "reopen": True}

    async def broadcast(message: dict) -> None:
        for ws in list(clients):
            try:
                await ws.send_json(message)
            except Exception:  # a page closed mid-send; it's dropped either way
                clients.discard(ws)

    async def failed(message: str) -> None:
        state["error"], state["reopen"] = message, True
        await broadcast({"error": message})
        await asyncio.sleep(retry_s)

    async def run() -> None:
        while True:
            try:
                if state["reopen"]:
                    state["reopen"] = False
                    state["gain"] = await asyncio.to_thread(source.open, meter.settings)
                samples = await asyncio.to_thread(source.read, READ_SAMPLES)
                if state["reopen"]:
                    continue  # settings changed during the read: this reading belongs to the old ones
                reading = meter.update(measure(samples), state["gain"])
                state["error"] = None
                await broadcast({"reading": reading})
            except SourceError as error:
                await failed(str(error))
            except Exception:
                log.exception("unexpected error in the reading loop")  # the traceback stays in the terminal
                await failed(UNEXPECTED)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        task = asyncio.create_task(run())
        yield
        task.cancel()
        source.close()
        meter.stop_recording()

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    @app.middleware("http")
    async def guard(request: Request, call_next):
        # T1: a hostile name pointed at 127.0.0.1 (DNS rebinding) still sends its own Host;
        # another site's page can post here, but it can't fake the Origin header.
        if request.headers.get("host") not in hosts:
            return JSONResponse({"error": "Wrong host name."}, 400, headers=HEADERS)
        if request.method == "POST" and request.headers.get("origin") not in origins:
            return JSONResponse({"error": "Requests must come from the meter's own page."}, 403, headers=HEADERS)
        response = await call_next(request)
        response.headers.update(HEADERS)
        return response

    def settings_json() -> dict:
        s = meter.settings
        return {"freq_mhz": s.freq_hz / 1_000_000, "gain_db": s.gain_db, "attenuator_db": s.attenuator_db}

    def status() -> dict:
        return {"settings": settings_json(), "gain_used": state["gain"], "error": state["error"],
                "recording": meter.recording.name if meter.recording else None}

    async def body(request: Request) -> dict:
        try:
            data = await request.json()
        except ValueError:
            data = None
        if not isinstance(data, dict):
            raise ValueError("Send a JSON object.")
        return data

    @app.get("/")
    async def page():
        return FileResponse(STATIC / "index.html")

    @app.get("/state")
    async def get_state():
        return status()

    @app.post("/settings")
    async def post_settings(request: Request):
        try:
            data = await body(request)
            settings = parse_settings(data.get("freq_mhz"), data.get("gain_db"), data.get("attenuator_db"))
        except ValueError as error:
            return JSONResponse({"error": str(error)}, 400)
        meter.apply(settings)
        state["reopen"] = True  # the loop retunes before its next reading
        return status()

    @app.post("/record")
    async def post_record(request: Request):
        try:
            on = (await body(request)).get("on")
        except ValueError as error:
            return JSONResponse({"error": str(error)}, 400)
        if not isinstance(on, bool):
            return JSONResponse({"error": "'on' must be true or false."}, 400)
        try:
            meter.start_recording() if on else meter.stop_recording()
        except OSError as error:
            return JSONResponse({"error": f"Couldn't start recording: {error.strerror or error}"}, 500)
        return status()

    @app.post("/peak/reset")
    async def post_reset():
        meter.reset_peak()
        return status()

    @app.websocket("/ws")
    async def stream(ws: WebSocket):
        # Browsers don't apply the same-origin policy to WebSockets, so check here (T1).
        if ws.headers.get("host") not in hosts or ws.headers.get("origin") not in origins:
            await ws.close(code=1008)  # policy violation
            return
        await ws.accept()
        clients.add(ws)
        try:
            if state["error"]:
                await ws.send_json({"error": state["error"]})
            while True:
                await ws.receive_text()  # nothing is expected from the page; this waits for it to close
        except WebSocketDisconnect:
            pass
        finally:
            clients.discard(ws)

    return app
