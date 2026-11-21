"""Start the ECHO control panel in your browser.

    python app.py                 # opens http://127.0.0.1:8765
    python app.py --port 9000     # pick another port
    python app.py --no-browser    # just print the address

Stop it with Ctrl+C. Use headphones: the 3-D effect is binaural.
"""
import argparse

try:
    from echo.webui import launch
except ModuleNotFoundError as exc:                      # friendlier than a traceback
    raise SystemExit(f"Missing package: {exc.name}. Install it with:  pip install pyquist")

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-browser", action="store_true", help="don't open the browser automatically")
    args = ap.parse_args()
    launch(port=args.port, open_browser=not args.no_browser)
