from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
import json
from threading import Thread
from uuid import uuid4


@contextmanager
def local_server():
    submissions = []
    html = files("autojob.testing").joinpath("form.html").read_bytes()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path != "/":
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(html)))
            self.end_headers()
            self.wfile.write(html)

        def do_POST(self):
            if self.path != "/submit":
                self.send_error(404)
                return
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= 10000:
                    raise ValueError("Tamaño inválido")
                data = json.loads(self.rfile.read(size))
                if not isinstance(data, dict) or not all(data.get(key) for key in ("name", "email", "modality", "file", "consent")):
                    raise ValueError("Datos incompletos")
            except (ValueError, TypeError):
                self.send_error(400)
                return
            receipt = "LOCAL-" + str(uuid4())
            submissions.append({**data, "receipt": receipt})
            body = json.dumps({"receipt": receipt}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/", submissions
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
