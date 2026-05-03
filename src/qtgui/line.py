from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QFrame


def create_horizontal_line(color=None, thickness=1):
    """
    Create a horizontal line using QFrame

    Args:
        color: QColor or string for line color (default: system color)
        thickness: int for line thickness in pixels (default: 1)

    Returns:
        QFrame configured as horizontal line
    """
    line = QFrame()
    line.setFrameShape(QFrame.Shape.HLine)
    line.setFrameShadow(QFrame.Shadow.Sunken)

    # Set thickness
    line.setFixedHeight(thickness)

    # Set color if provided
    if color:
        if isinstance(color, str):
            line.setStyleSheet(
                f"QFrame {{ background-color: {color.lower()}; }}")
        elif isinstance(color, QColor):
            line.setStyleSheet(
                f"QFrame {{ color: rgb({color.red()}, {color.green()}, {color.blue()}); }}")

    return line


def create_vertical_line(color=None, thickness=1):
    """
    Create a vertical line using QFrame

    Args:
        color: QColor or string for line color (default: system color)
        thickness: int for line thickness in pixels (default: 1)

    Returns:
        QFrame configured as vertical line
    """
    line = QFrame()
    line.setFrameShape(QFrame.Shape.VLine)
    line.setFrameShadow(QFrame.Shadow.Sunken)

    # Set thickness
    line.setFixedWidth(thickness)

    # Set color if provided
    if color:
        if isinstance(color, str):
            line.setStyleSheet(f"QFrame {{ color: {color}; }}")
        elif isinstance(color, QColor):
            line.setStyleSheet(
                f"QFrame {{ color: rgb({color.red()}, {color.green()}, {color.blue()}); }}")

    return line


def create_custom_horizontal_line(color="gray", thickness=1,
                                  margins=(0, 5, 0, 5)):
    """
    Create a customized horizontal line with more styling options

    Args:
        color: Color of the line
        thickness: Thickness in pixels
        margins: Tuple of (left, top, right, bottom) margins

    Returns:
        QFrame configured as horizontal line
    """
    line = QFrame()
    line.setFrameShape(QFrame.Shape.HLine)
    line.setFrameShadow(QFrame.Shadow.Plain)

    # Apply styling
    style = f"""
        QFrame {{
            background-color: {color};
            border: none;
            max-height: {thickness}px;
            min-height: {thickness}px;
        }}
    """
    line.setStyleSheet(style)

    # Set margins
    line.setContentsMargins(*margins)

    return line


def create_custom_vertical_line(color="gray", thickness=1,
                                margins=(5, 0, 5, 0)):
    """
    Create a customized vertical line with more styling options

    Args:
        color: Color of the line
        thickness: Thickness in pixels
        margins: Tuple of (left, top, right, bottom) margins

    Returns:
        QFrame configured as vertical line
    """
    line = QFrame()
    line.setFrameShape(QFrame.Shape.VLine)
    line.setFrameShadow(QFrame.Shadow.Plain)

    # Apply styling
    style = f"""
        QFrame {{
            background-color: {color};
            border: none;
            max-width: {thickness}px;
            min-width: {thickness}px;
        }}
    """
    line.setStyleSheet(style)

    # Set margins
    line.setContentsMargins(*margins)

    return line
