import argparse
import multiprocessing
import os
import sys

# A PyInstaller windowed executable can inherit the Windows ANSI code page even
# when the parent sets PYTHONIOENCODING. Force pipe output to UTF-8 before
# importing the API, because startup checks may log during module import.
for stream in (sys.stdout, sys.stderr):
    if stream is not None and hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="backslashreplace")

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
