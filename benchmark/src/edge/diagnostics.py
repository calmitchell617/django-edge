"""Control-operation diagnostics without exception messages or frame locals."""

import re
import traceback


def error_details(error):
    frames = []
    seen = set()
    current = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        for frame in traceback.extract_tb(current.__traceback__):
            frames.append(f"{frame.filename.rsplit('/', 1)[-1]}:{frame.lineno}:{frame.name}")
        # RPC may wrap a Python traceback in a JavaScript exception. Extract only
        # file locations, never source lines, exception messages, or values.
        if type(current).__name__ == "JsException":
            for filename, line, function in re.findall(
                r'File "([^"\n]+)", line (\d+), in ([A-Za-z_][A-Za-z0-9_]*)', str(current)
            ):
                frames.append(f"{filename.rsplit('/', 1)[-1]}:{line}:{function}")
        current = current.__cause__ or current.__context__
    return {"error": type(error).__name__, "locations": frames[-12:]}
