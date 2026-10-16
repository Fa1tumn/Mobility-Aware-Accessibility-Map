from threading import Thread
from urllib.error import HTTPError
from urllib.request import urlopen

import pytest

from scripts.open_grid import create_server


def test_server_only_serves_the_selected_html(tmp_path):
    page = tmp_path / "grid map.html"
    page.write_text("<h1>Grid</h1>", encoding="utf-8")
    (tmp_path / ".env").write_text("PRIVATE=test", encoding="utf-8")
    server = create_server(page, 0)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        with urlopen(base + "/grid%20map.html") as response:
            assert response.read() == b"<h1>Grid</h1>"
            assert response.headers.get_content_type() == "text/html"
        for path in ("/", "/.env", "/../.env", "/%2e%2e/.env"):
            with pytest.raises(HTTPError) as error:
                urlopen(base + path)
            assert error.value.code == 404
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
