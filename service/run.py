"""The Gold Volt application server: Waitress on 127.0.0.1 only."""
import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOST = "127.0.0.1"
DEFAULT_PORT = 8765


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--config", help="Path to the protected config file")
    args = parser.parse_args()

    sys.path.insert(0, str(ROOT))
    os.chdir(ROOT)
    if args.config:
        os.environ["GOLDVOLT_CONFIG"] = str(Path(args.config).resolve())
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "goldvolt.settings")

    from django.core.wsgi import get_wsgi_application
    from waitress import serve

    serve(get_wsgi_application(), host=HOST, port=args.port, threads=8, ident="goldvolt")


if __name__ == "__main__":
    main()
