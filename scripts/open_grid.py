import argparse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit


ROOT = Path(__file__).resolve().parents[1]


class GridHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if unquote(urlsplit(self.path).path) != "/" + self.server.page.name:
            self.send_error(404)
            return
        try:
            content = self.server.page.read_bytes()
        except OSError:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)


def create_server(page, port):
    server = ThreadingHTTPServer(("127.0.0.1", port), GridHandler)
    server.page = Path(page).resolve()
    return server


def main():
    parser = argparse.ArgumentParser(description="Open a grid HTML page using a local web server.")
    parser.add_argument("page", nargs="?", type=Path, default=ROOT / "output/grid/yonsei_demo.html")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    page = args.page.resolve()
    if page.suffix.lower() != ".html" or not page.is_file():
        parser.exit(1, f"HTML file not found: {page}\nGenerate it with python -m scripts.test_grid --yonsei-demo\n")
    try:
        server = create_server(page, args.port)
    except (OSError, OverflowError) as error:
        parser.exit(1, f"Could not start the server: {error}\nTry a different --port, such as 8766.\n")
    url = f"http://127.0.0.1:{server.server_port}/{quote(page.name)}"
    print(f"Grid map: {url}", flush=True)
    print("Keep this terminal open. Press Ctrl+C to stop.", flush=True)
    with server:
        if not args.no_browser:
            webbrowser.open(url)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\nGrid server stopped.")


if __name__ == "__main__":
    main()
