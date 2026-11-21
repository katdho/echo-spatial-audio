"""app.py: starts ECHO's control panel.

Run this file to use ECHO:  python src/app.py
It starts a small local web server (echo/webui.py) and opens the control panel
in your browser at http://127.0.0.1:8765. Stop it with Ctrl+C

Options:  --port 9000  (use another port)   --no-browser  (just print the address)
Use headphones: the 3-D effect is binaural.
"""
import argparse

try:
    from echo.webui import launch
except ModuleNotFoundError as exc:                      
    raise SystemExit(f"Missing package: {exc.name}. Install it with:  pip install pyquist")

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-browser", action="store_true", help="don't open the browser automatically")
    args = ap.parse_args()
    launch(port=args.port, open_browser=not args.no_browser)
