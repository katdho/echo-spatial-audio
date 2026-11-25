
"""app.py: starts ECHO's control panel.

Run locally:
    python src/app.py

Options:
    --port 9000
    --no-browser

On Render, automatically uses the assigned PORT, binds to
0.0.0.0, and does not attempt to open a browser.
"""

import argparse
import os

try:
    from echo.webui import launch
except ModuleNotFoundError as exc:
    raise SystemExit(
        f"Missing package: {exc.name}. "
        "Install dependencies with: pip install -r requirements.txt"
    )

if __name__ == "__main__":
    is_render = "PORT" in os.environ
    default_port = int(os.environ.get("PORT", 8765))

    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--port", type=int, default=default_port)
    ap.add_argument(
        "--no-browser",
        action="store_true",
        help="don't open the browser automatically"
    )
    args = ap.parse_args()

    launch(
        port=args.port,
        host="0.0.0.0" if is_render else "127.0.0.1",
        open_browser=not args.no_browser and not is_render,
        find_free_port=not is_render
    )
