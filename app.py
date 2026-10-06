"""Run the standalone Cleaning App server."""

import argparse
import os

from waitress import serve

from cleaning_app import create_app


def main():
    parser = argparse.ArgumentParser(description="Cleaning App web server")
    parser.add_argument("--host", default=os.getenv("CLEANING_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("CLEANING_PORT", "8000")))
    args = parser.parse_args()
    app = create_app()
    print(f"Cleaning App listening on http://{args.host}:{args.port}", flush=True)
    serve(app, host=args.host, port=args.port, threads=4)


if __name__ == "__main__":
    main()
