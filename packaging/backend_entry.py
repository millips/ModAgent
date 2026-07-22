import argparse
import multiprocessing
import os

import uvicorn

from modagent.api import app


def main():
    parser = argparse.ArgumentParser(description="ModAgent local backend")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=int(os.environ.get("MODAGENT_API_PORT", "18890")))
    args = parser.parse_args()
    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        log_config=None,
        access_log=False,
    )


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
