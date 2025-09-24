import sys
from loguru import logger as log


def loguru_setup(filename: str | None = None, level: str = "INFO") -> None:
    """Configure loguru sinks for console and optional file output.

    Args:
        filename: Optional path to a file where logs will be written.
        level: Minimum log level for emitted records (e.g., "INFO", "DEBUG").
    """
    fmt_string = "[<c>{time:YYYY-MM-DD HH:mm:ss,SSS}</>][<e>{module}</>][<g>{level}</>] - {message}"
    log.remove()
    log.add(
        sys.stderr,
        format=fmt_string,
        level=level,
    )
    if filename is not None:
        log.add(
            filename,
            format=fmt_string,
            level=level,
        )
        log.info(f"Logging to {filename}")
