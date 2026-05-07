from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QSize, Qt, QDir
from PyQt6.QtGui import QColor, QIcon, QPixmap, QPainter

from qtgui.pixmap import colorize_pixmap
from svg_icons.paths import LINE_ICONS, FILL_ICONS, OTHER_ICONS

# Example:
# LINE_ICONS = Path(__file__).parent / "icons" / "line"
# FILL_ICONS = Path(__file__).parent / "icons" / "fill"
# OTHER_ICONS = Path(__file__).parent / "icons" / "other"

# Map Qt search-path prefix → absolute directory
_ICON_SEARCH_PATHS: dict[str, Path] = {
    "line-icons": LINE_ICONS,
    "fill-icons": FILL_ICONS,
    "other-icons": OTHER_ICONS,
}

_ICON_CACHE: dict[tuple[str, int, int, int, int, int, int], QIcon] = {}
_SEARCH_PATHS_REGISTERED = False


def _register_icon_search_paths() -> None:
    """
    Register Qt search paths so strings like
    'line-icons:search-line.svg' resolve correctly.
    """
    global _SEARCH_PATHS_REGISTERED

    if _SEARCH_PATHS_REGISTERED:
        return

    for prefix, directory in _ICON_SEARCH_PATHS.items():
        QDir.addSearchPath(prefix, str(directory.resolve()))

    _SEARCH_PATHS_REGISTERED = True


def get_icon(
    icon_path: str,
    size: Optional[QSize] = None,
    color: Optional[QColor] = None,
) -> QIcon:
    """
    Get a QIcon from a Qt search-path resource.

    Args:
        icon_path:
            Icon path using a registered Qt search-path prefix,
            for example: 'line-icons:search-line.svg'.
        size:
            Target icon size. Defaults to QSize(256, 256).
        color:
            Optional icon color. Defaults to black.

    Returns:
        QIcon instance.

    Raises:
        FileNotFoundError:
            If the icon cannot be loaded.
    """
    _register_icon_search_paths()

    size = size or QSize(256, 256)
    color = color or QColor("black")

    cache_key = (
        icon_path,
        size.width(),
        size.height(),
        color.red(),
        color.green(),
        color.blue(),
        color.alpha(),
    )

    cached = _ICON_CACHE.get(cache_key)
    if cached is not None:
        return cached

    pixmap = QPixmap(icon_path)

    if pixmap.isNull():
        raise FileNotFoundError(f"Could not load icon: {icon_path!r}")

    resized = pixmap.scaled(
        size,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )

    tinted = colorize_pixmap(resized, color)
    icon = QIcon(tinted)

    _ICON_CACHE[cache_key] = icon
    return icon


def _get_line_icon(
    icon_name: str,
    size: Optional[QSize] = None,
    color: Optional[QColor] = None,
) -> QIcon:
    icon_path = f"line-icons:{icon_name}.svg"
    return get_icon(icon_path, size=size, color=color)


def _get_fill_icon(
    icon_name: str,
    size: Optional[QSize] = None,
    color: Optional[QColor] = None,
) -> QIcon:
    icon_path = f"fill-icons:{icon_name}.svg"
    return get_icon(icon_path, size=size, color=color)


def _get_other_icon(
    icon_name: str,
    size: Optional[QSize] = None,
    color: Optional[QColor] = None,
) -> QIcon:
    icon_path = f"other-icons:{icon_name}.svg"
    return get_icon(icon_path, size=size, color=color)