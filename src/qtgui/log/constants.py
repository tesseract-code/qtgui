import logging
from typing import Final

from cross_platform.dev.icons_legacy.svg_path import (IconType)


BADGE_HEIGHT: Final[int] = 24
MAX_LOG_LINES: Final[int] = 10000
DEFAULT_FONT_SIZE: Final[int] = 10

# UI Color scheme based on log levels
LOG_LEVEL_COLORS: Final[dict] = {
    logging.CRITICAL: "#DC3545",  # Red
    logging.ERROR: "#FD7E14",  # Orange
    logging.WARNING: "#FFC107",  # Yellow
    logging.INFO: "#17A2B8",  # Blue
    logging.DEBUG: "#6C757D"  # Gray
}

LOG_LEVEL_ICONS: Final[dict] = {
    logging.CRITICAL: "line-icons:critical-line.svg",
    logging.ERROR: "line-icons:close-circle-line.svg",
    logging.WARNING: "line-icons:error-warning-line.svg",
    logging.INFO: "line-icons:information-line.svg",
    logging.DEBUG: "line-icons:bug-2-line.svg",
}
