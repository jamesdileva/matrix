"""The packaged Flood server: API, workers' queue, and the console in one
process (S54).

Run directly (`python flood_server.py`) or built into an exe by
`scripts/package.py`. The console is served at / when frontend/dist has
been built; the API stays under /api.
"""

import argparse

import uvicorn

from app.config.settings import settings
from app.main import app


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the packaged Flood server.")
    parser.add_argument("--host", default=settings.host)
    parser.add_argument("--port", type=int, default=settings.port)
    args = parser.parse_args()
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
