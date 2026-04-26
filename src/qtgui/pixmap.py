from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from PyQt6 import QtWidgets, QtCore, QtGui
from PyQt6.QtCore import QByteArray, QSize, Qt
from PyQt6.QtGui import QPixmap, QImage, QPainter, QColor
from PyQt6.QtSvg import QSvgRenderer


def create_transparent_pixmap(source: QtGui.QPixmap,
                              opacity: float) -> QtGui.QPixmap:
    """
    Creates a semi-transparent pixmap from the given pixmap source.

    Args:
        source: Source pixmap to make transparent
        opacity: Opacity from completely transparent (0.0) to completely opaque (1.0)

    Returns:
        QtGui.QPixmap: Semi-transparent pixmap

    Note: This utility is still useful in PyQt6 for creating custom transparency effects.
    """
    if source.isNull():
        return QtGui.QPixmap()

    transparent_pixmap = QtGui.QPixmap(source.size())
    transparent_pixmap.fill(QtCore.Qt.GlobalColor.transparent)

    painter = QtGui.QPainter(transparent_pixmap)
    painter.setOpacity(opacity)
    painter.drawPixmap(0, 0, source)
    painter.end()  # Explicit painter cleanup for PyQt6

    return transparent_pixmap


def make_icon_with_states(
        style: QtWidgets.QStyle,
        parent: QtWidgets.QWidget,
        standard_pixmap: QtWidgets.QStyle.StandardPixmap, *,
        disabled_opacity: float = 0.25,
        hover_opacity: float = 0.8
) -> QtGui.QIcon:
    """
    Create an icon with multiple states from a standard pixmap.

    Args:
        style: QStyle instance for getting standard pixmaps
        parent: Parent widget for style context
        standard_pixmap: Standard pixmap identifier
        disabled_opacity: Opacity for disabled state
        hover_opacity: Opacity for hover state

    Returns:
        QtGui.QIcon: Icon with normal, disabled, and hover states

    Note: Updated for PyQt6 with better state handling and explicit cleanup.
    """
    icon = QtGui.QIcon()

    # Get the base pixmap
    normal_pixmap = style.standardPixmap(standard_pixmap, None, parent)

    if normal_pixmap.isNull():
        return icon

    # Add normal state
    icon.addPixmap(normal_pixmap, QtGui.QIcon.Mode.Normal,
                   QtGui.QIcon.State.Off)

    # Add disabled state with transparency
    disabled_pixmap = create_transparent_pixmap(normal_pixmap, disabled_opacity)
    icon.addPixmap(disabled_pixmap, QtGui.QIcon.Mode.Disabled,
                   QtGui.QIcon.State.Off)

    # Add hover state (active mode in Qt)
    if hover_opacity != 1.0:
        hover_pixmap = create_transparent_pixmap(normal_pixmap, hover_opacity)
        icon.addPixmap(hover_pixmap, QtGui.QIcon.Mode.Active,
                       QtGui.QIcon.State.Off)

    return icon


def set_button_icon(
        style: QtWidgets.QStyle,
        button: QtWidgets.QAbstractButton,
        standard_pixmap: QtWidgets.QStyle.StandardPixmap, *,
        disabled_opacity: float = 0.25
) -> QtGui.QIcon:
    """
    Set a button icon with proper state handling.

    Args:
        style: QStyle instance
        button: Button to set icon on
        standard_pixmap: Standard pixmap identifier
        disabled_opacity: Opacity for disabled state

    Returns:
        QtGui.QIcon: The created icon

    Note: Still useful in PyQt6, updated with better error handling.
    """
    icon = make_icon_with_states(
        style,
        parent=button,
        standard_pixmap=standard_pixmap,
        disabled_opacity=disabled_opacity
    )

    button.setIcon(icon)
    return icon


def create_colored_pixmap(
        size: QtCore.QSize,
        color: QtGui.QColor,
        shape: str = 'rectangle'
) -> QtGui.QPixmap:
    """
    Create a solid colored pixmap with optional shapes.

    Args:
        size: Size of the pixmap
        color: Fill color
        shape: Shape type ('rectangle', 'circle', 'rounded_rect')

    Returns:
        QtGui.QPixmap: Colored pixmap

    Note: New utility useful for creating custom icons and backgrounds.
    """
    pixmap = QtGui.QPixmap(size)
    pixmap.fill(QtCore.Qt.GlobalColor.transparent)

    painter = QtGui.QPainter(pixmap)
    painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
    painter.setBrush(QtGui.QBrush(color))
    painter.setPen(QtCore.Qt.PenStyle.NoPen)

    rect = QtCore.QRect(0, 0, size.width(), size.height())

    if shape == 'circle':
        painter.drawEllipse(rect)
    elif shape == 'rounded_rect':
        radius = min(size.width(), size.height()) // 8
        painter.drawRoundedRect(rect, radius, radius)
    else:  # rectangle
        painter.drawRect(rect)

    painter.end()
    return pixmap


def create_icon_from_text(
        text: str,
        size: QtCore.QSize,
        text_color: QtGui.QColor = QtGui.QColor(255, 255, 255),
        background_color: QtGui.QColor = QtGui.QColor(100, 100, 100),
        font_family: str = "Arial"
) -> QtGui.QIcon:
    """
    Create an icon from text (useful for initials, symbols, etc.).

    Args:
        text: Text to render
        size: Icon size
        text_color: Text color
        background_color: Background color
        font_family: Font family name

    Returns:
        QtGui.QIcon: Icon with rendered text

    Note: New utility particularly useful for avatars, badges, and custom symbols.
    """
    pixmap = QtGui.QPixmap(size)
    pixmap.fill(QtCore.Qt.GlobalColor.transparent)

    painter = QtGui.QPainter(pixmap)
    painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QtGui.QPainter.RenderHint.TextAntialiasing, True)

    # Draw background circle
    painter.setBrush(QtGui.QBrush(background_color))
    painter.setPen(QtCore.Qt.PenStyle.NoPen)
    rect = QtCore.QRect(0, 0, size.width(), size.height())
    painter.drawEllipse(rect)

    # Draw text
    painter.setPen(text_color)
    font = QtGui.QFont(font_family,size.height())
    font.setBold(True)
    painter.setFont(font)

    painter.drawText(rect, QtCore.Qt.AlignmentFlag.AlignCenter, text)
    painter.end()

    icon = QtGui.QIcon(pixmap)
    return icon


def apply_icon_theme_colors(
        icon: QtGui.QIcon,
        normal_color: QtGui.QColor,
        disabled_color: Optional[QtGui.QColor] = None
) -> QtGui.QIcon:
    """
    Apply theme colors to an existing icon by recoloring it.

    Args:
        icon: Source icon
        normal_color: Color for normal state
        disabled_color: Color for disabled state (defaults to 50% opacity normal)

    Returns:
        QtGui.QIcon: Recolored icon

    Note: New utility for theming icons to match application color schemes.
    """
    if disabled_color is None:
        disabled_color = QtGui.QColor(normal_color)
        disabled_color.setAlpha(128)  # 50% opacity

    new_icon = QtGui.QIcon()

    # Get available sizes
    sizes = icon.availableSizes()
    if not sizes:
        sizes = [QtCore.QSize(16, 16), QtCore.QSize(24, 24),
                 QtCore.QSize(32, 32)]

    for size in sizes:
        # Normal state
        pixmap = icon.pixmap(size, QtGui.QIcon.Mode.Normal)
        colored_pixmap = colorize_pixmap(pixmap, normal_color)
        new_icon.addPixmap(colored_pixmap, QtGui.QIcon.Mode.Normal)

        # Disabled state
        disabled_pixmap = colorize_pixmap(pixmap, disabled_color)
        new_icon.addPixmap(disabled_pixmap, QtGui.QIcon.Mode.Disabled)

    return new_icon


def colorize_pixmap(pixmap: QtGui.QPixmap,
                    color: QtGui.QColor) -> QtGui.QPixmap:
    """
    Colorize a pixmap with the given color while preserving alpha.

    Args:
        pixmap: Source pixmap
        color: Target color

    Returns:
        QtGui.QPixmap: Colorized pixmap

    Note: Helper function for icon theming.
    """
    if pixmap.isNull():
        return pixmap

    colored_pixmap = QtGui.QPixmap(pixmap.size())
    colored_pixmap.fill(QtCore.Qt.GlobalColor.transparent)

    painter = QtGui.QPainter(colored_pixmap)
    painter.setCompositionMode(
        QtGui.QPainter.CompositionMode.CompositionMode_SourceOver)

    # Draw the original pixmap
    painter.drawPixmap(0, 0, pixmap)

    # Apply color overlay
    painter.setCompositionMode(
        QtGui.QPainter.CompositionMode.CompositionMode_SourceIn)
    painter.fillRect(colored_pixmap.rect(), color)

    painter.end()
    return colored_pixmap


def create_scalable_icon(*pixmap_sizes_and_paths) -> QtGui.QIcon:
    """
    Create a scalable icon from multiple pixmap files at different sizes.

    Args:
        *pixmap_sizes_and_paths: Tuples of (size, file_path) or (width, height, file_path)

    Returns:
        QtGui.QIcon: Scalable icon

    Example:
        icon = create_scalable_icon(
            (16, "icon_16.png"),
            (24, "icon_24.png"),
            (32, 32, "icon_32.png")
        )

    Note: Useful for creating high-quality icons that scale well across different DPI settings.
    """
    icon = QtGui.QIcon()

    for args in pixmap_sizes_and_paths:
        if len(args) == 2:
            size, path = args
            icon.addFile(path, QtCore.QSize(size, size))
        elif len(args) == 3:
            width, height, path = args
            icon.addFile(path, QtCore.QSize(width, height))

    return icon


def create_pixmap_from_svg(file_path: Path, size: QSize) -> QPixmap:
    """Loads an SVG file, renders it to a QImage, and converts it to a QPixmap."""
    try:
        # Load SVG content from file
        with open(file_path.resolve(), "r", encoding="utf-8") as f:
            svg_data = f.read()

        renderer = QSvgRenderer(QByteArray(svg_data.encode()))
        if not renderer.isValid():
            print(f"Error: Invalid SVG file at {file_path}")
            return QPixmap()

        # Create a QImage to render the SVG onto
        image = QImage(size, QImage.Format.Format_ARGB32)
        image.fill(Qt.GlobalColor.transparent)

        # Render the SVG onto the image
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.LosslessImageRendering, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        renderer.render(painter)
        painter.end()

        # Convert the QImage to a QPixmap
        return QPixmap.fromImage(image)
    except FileNotFoundError:
        print(f"Error: Icon file not found at {file_path}")
        return QPixmap()


@dataclass(frozen=False)
class PixmapSettings:
    """

    """
    normal: QPixmap
    size: QSize
    disabled: Optional[QPixmap] = None
    on_color: Optional[QColor] = None
    off_color: Optional[QColor] = None

    _default_size = QSize(24, 24)

    @classmethod
    def from_path(cls,
                  normal_path: Path,
                  disabled_path: Optional[Path] = None,
                  size: Optional[QSize] = None,
                  on_color: Optional[QColor] = None,
                  off_color: Optional[QColor] = None):
        """

        """
        if not normal_path:
            raise ValueError("The path for the normal pixmap not provided!")
        if not normal_path.exists():
            raise FileExistsError("The path for the normal pixmap does not "
                                  "exist")
        if not size:
            size = cls._default_size

        normal_pixmap = create_pixmap_from_svg(file_path=normal_path, size=size)

        disabled_pixmap = None
        if disabled_path and disabled_path.exists():
            disabled_pixmap = create_pixmap_from_svg(file_path=disabled_path,
                                                     size=size)
        settings = PixmapSettings(normal=normal_pixmap,
                                  disabled=disabled_pixmap,
                                  size=size,
                                  on_color=on_color,
                                  off_color=off_color)
        return settings
