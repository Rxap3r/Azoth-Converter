"""Light and dark look (design "A", Nov 2026), and following the Windows setting.

All colours live in the two ``Colors`` sets below; the stylesheet is built from them, so a
widget only says *what* it is (``setProperty("role", "tile")``), never which colour it has.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QWidget

from .resources import resources_dir

SYSTEM, LIGHT, DARK = "system", "light", "dark"
CHOICES = [(SYSTEM, "Follow Windows"), (LIGHT, "Light"), (DARK, "Dark")]
FONT = '"Segoe UI Variable Text", "Segoe UI", "Inter", "Noto Sans", sans-serif'
CATEGORIES = ("image", "pdf", "document", "spreadsheet", "presentation", "video", "audio")


@dataclass(frozen=True)
class Colors:
    mode: str
    window: str  # sidebar and window background
    content: str  # the page area
    surface: str  # cards, right panel, inputs
    hover: str
    border: str
    border_strong: str
    text: str
    muted: str  # secondary text (≥ 4.5:1 on surface and content)
    accent: str
    accent_hover: str
    accent_text: str  # text on the accent colour
    accent_soft: str  # selected tile
    accent_soft_text: str
    drop: str
    drop_border: str
    note: str
    success: str
    error: str
    warn_bg: str
    warn_text: str
    libreoffice_bg: str
    libreoffice_border: str
    libreoffice_text: str
    clean_bg: str
    clean_text: str
    badges: dict  # category -> (background, text)


LIGHT_COLORS = Colors(
    mode=LIGHT,
    window="#F3F3F5",
    content="#FBFBFC",
    surface="#FFFFFF",
    hover="#F0F0F4",
    border="#E4E4E9",
    border_strong="#D2D2DA",
    text="#1B1B1F",
    muted="#55555F",
    accent="#3F43C9",
    accent_hover="#3538B0",
    accent_text="#FFFFFF",
    accent_soft="#EEF0FF",
    accent_soft_text="#2B2D7A",
    drop="#F5F5FC",
    drop_border="#AFB1D6",
    note="#F4F4F7",
    success="#0E7A3C",
    error="#B42318",
    warn_bg="#FFF4CE",
    warn_text="#5C4400",
    libreoffice_bg="#FFF8E8",
    libreoffice_border="#8E6A1B",
    libreoffice_text="#5C4200",
    clean_bg="#E8F5EC",
    clean_text="#0D6B35",
    badges={
        "image": ("#E3F1FB", "#0B4F7A"),
        "pdf": ("#FDE7E4", "#8A1F11"),
        "document": ("#E4ECFB", "#1C3F8A"),
        "spreadsheet": ("#E2F4E8", "#0D5B2E"),
        "presentation": ("#FCEBDD", "#8A3B12"),
        "video": ("#F1E6FB", "#5B2283"),
        "audio": ("#DDF3F1", "#0B5A55"),
        "unknown": ("#EEEEF2", "#44444F"),
    },
)

DARK_COLORS = Colors(
    mode=DARK,
    window="#1B1B21",
    content="#212128",
    surface="#2A2A33",
    hover="#33333D",
    border="#33333E",
    border_strong="#474754",
    text="#ECECF2",
    muted="#ADADBE",
    accent="#8E92F7",
    accent_hover="#A6A9FA",
    accent_text="#15153D",
    accent_soft="#2F3166",
    accent_soft_text="#E0E1FF",
    drop="#25253A",
    drop_border="#55578F",
    note="#26262F",
    success="#74D69E",
    error="#FF9B8F",
    warn_bg="#3D3200",
    warn_text="#FFE08A",
    libreoffice_bg="#3A2E12",
    libreoffice_border="#C9A24A",
    libreoffice_text="#FFE2A3",
    clean_bg="#1C3A28",
    clean_text="#9EE2B5",
    badges={
        "image": ("#16344A", "#A6D8F7"),
        "pdf": ("#4A1E19", "#FFB9AE"),
        "document": ("#1E2B4F", "#BCCBFF"),
        "spreadsheet": ("#173826", "#A3E5BA"),
        "presentation": ("#46291A", "#FFC9A3"),
        "video": ("#36224A", "#DDBDF7"),
        "audio": ("#163A38", "#9FE3DC"),
        "unknown": ("#33333D", "#D0D0DA"),
    },
)


def colors_for(mode: str) -> Colors:
    return DARK_COLORS if mode == DARK else LIGHT_COLORS


def palette(c: Colors) -> QPalette:
    """Colours for Qt's own drawing: menus, dialogs, tooltips, scroll bars, check boxes."""
    p = QPalette()
    roles = {
        QPalette.ColorRole.Window: c.window,
        QPalette.ColorRole.WindowText: c.text,
        QPalette.ColorRole.Base: c.surface,
        QPalette.ColorRole.AlternateBase: c.note,
        QPalette.ColorRole.Text: c.text,
        QPalette.ColorRole.Button: c.surface,
        QPalette.ColorRole.ButtonText: c.text,
        QPalette.ColorRole.BrightText: c.error,
        QPalette.ColorRole.Highlight: c.accent,
        QPalette.ColorRole.HighlightedText: c.accent_text,
        QPalette.ColorRole.ToolTipBase: c.surface,
        QPalette.ColorRole.ToolTipText: c.text,
        QPalette.ColorRole.PlaceholderText: c.muted,
        QPalette.ColorRole.Link: c.accent,
        QPalette.ColorRole.LinkVisited: c.accent,
        QPalette.ColorRole.Light: c.surface,
        QPalette.ColorRole.Midlight: c.border,
        QPalette.ColorRole.Mid: c.border_strong,
        QPalette.ColorRole.Dark: c.border_strong,
        QPalette.ColorRole.Shadow: "#000000",
    }
    for role, value in roles.items():
        p.setColor(role, QColor(value))
    for role in (
        QPalette.ColorRole.Text,
        QPalette.ColorRole.ButtonText,
        QPalette.ColorRole.WindowText,
    ):
        p.setColor(QPalette.ColorGroup.Disabled, role, QColor(c.muted))
    return p


def stylesheet(c: Colors) -> str:
    badges = "\n".join(
        f'QLabel[role="badge"][category="{cat}"] {{ background: {bg}; color: {fg}; }}'
        for cat, (bg, fg) in c.badges.items()
    )
    check_image = (resources_dir() / f"check-{c.mode}.svg").as_posix()
    return f"""
* {{ font-family: {FONT}; font-size: 14px; color: {c.text}; }}
QMainWindow, #Sidebar {{ background: {c.window}; }}
QToolTip {{ background: {c.surface}; color: {c.text}; border: 1px solid {c.border_strong}; padding: 4px 6px; }}

#Content {{ background: {c.content}; border-left: 1px solid {c.border}; border-top: 1px solid {c.border};
    border-top-left-radius: 10px; }}
#Content > QWidget, QScrollArea, QScrollArea > QWidget > QWidget, QStackedWidget {{ background: transparent; }}
#RightPanel {{ background: {c.surface}; border-left: 1px solid {c.border}; }}

QLabel {{ background: transparent; }}
QLabel[role="brand"] {{ font-size: 15px; font-weight: 600; }}
QLabel[role="h1"] {{ font-size: 26px; font-weight: 600; }}
QLabel[role="h2"] {{ font-size: 16px; font-weight: 600; }}
QLabel[role="muted"] {{ color: {c.muted}; }}
QLabel[role="small"] {{ color: {c.muted}; font-size: 12px; }}
QLabel[role="caption"] {{ color: {c.muted}; font-size: 12px; font-weight: 600; }}
QLabel[role="note"] {{ background: {c.note}; color: {c.text}; border-radius: 8px; padding: 10px 12px;
    font-size: 12px; }}
QLabel[role="banner"] {{ background: {c.warn_bg}; color: {c.warn_text}; border-radius: 8px; padding: 10px 12px; }}
QLabel[role="offline"] {{ background: {c.accent_soft}; color: {c.accent_soft_text}; border-radius: 8px;
    padding: 10px 12px; font-size: 12px; }}
QLabel[role="status"][state="done"] {{ color: {c.success}; font-weight: 600; font-size: 12px; }}
QLabel[role="status"][state="failed"] {{ color: {c.error}; font-size: 12px; }}
QLabel[role="status"] {{ color: {c.muted}; font-size: 12px; }}
QLabel[role="badge"] {{ border-radius: 8px; font-size: 11px; font-weight: 700; }}
{badges}
QLabel[role="chip"] {{ background: {c.note}; border: 1px solid {c.border}; border-radius: 6px;
    padding: 3px 9px; font-size: 12px; font-weight: 600; }}
QLabel[role="chip"][libreoffice="true"] {{ background: {c.libreoffice_bg}; color: {c.libreoffice_text};
    border: 1px dashed {c.libreoffice_border}; }}
QLabel[role="chip"][clean="true"] {{ background: {c.clean_bg}; color: {c.clean_text}; border: 1px solid {c.clean_bg}; }}

QPushButton {{ background: {c.surface}; border: 1px solid {c.border_strong}; border-radius: 6px;
    padding: 6px 14px; min-height: 20px; }}
QPushButton:hover {{ background: {c.hover}; }}
QPushButton:focus {{ border: 2px solid {c.accent}; padding: 5px 13px; }}
QPushButton:disabled {{ color: {c.muted}; background: {c.note}; }}
QPushButton[role="primary"] {{ background: {c.accent}; color: {c.accent_text}; border: 0; border-radius: 8px;
    font-size: 15px; font-weight: 600; min-height: 44px; padding: 0 16px; }}
QPushButton[role="primary"]:hover {{ background: {c.accent_hover}; }}
QPushButton[role="primary"]:focus {{ border: 2px solid {c.text}; }}
QPushButton[role="primary"]:disabled {{ background: {c.border_strong}; color: {c.muted}; }}
QPushButton[role="nav"] {{ background: transparent; border: 0; border-radius: 6px; text-align: left;
    padding: 0 12px; min-height: 40px; }}
QPushButton[role="nav"]:hover {{ background: {c.hover}; }}
QPushButton[role="nav"]:checked {{ background: {c.surface}; font-weight: 600; border-left: 3px solid {c.accent};
    padding-left: 9px; }}
QPushButton[role="nav"]:focus {{ border: 2px solid {c.accent}; }}
QPushButton[role="tile"] {{ background: {c.surface}; border: 1px solid {c.border}; border-radius: 8px;
    padding: 0; text-align: left; min-height: 48px; }}
QPushButton[role="tile"][wide="true"] {{ min-height: 54px; }}
QPushButton[role="tile"]:hover {{ background: {c.hover}; }}
QPushButton[role="tile"]:checked {{ background: {c.accent_soft}; border: 2px solid {c.accent}; }}
QPushButton[role="tile"]:focus {{ border: 2px solid {c.accent}; }}
QPushButton[role="segment"] {{ background: transparent; border: 0; border-radius: 6px; min-height: 30px;
    padding: 0 6px; font-size: 13px; }}
QPushButton[role="segment"]:checked {{ background: {c.surface}; font-weight: 600; border: 1px solid {c.border_strong}; }}
QPushButton[role="segment"]:focus {{ border: 2px solid {c.accent}; }}
#Segmented {{ background: {c.note}; border-radius: 8px; }}
QPushButton[role="icon"] {{ background: transparent; border: 0; border-radius: 6px; padding: 0;
    min-width: 36px; max-width: 36px; min-height: 36px; max-height: 36px; }}
QPushButton[role="icon"]:hover {{ background: {c.hover}; }}
QPushButton[role="icon"]:focus {{ border: 2px solid {c.accent}; }}
QPushButton[role="link"] {{ background: transparent; border: 0; padding: 0 2px; color: {c.accent};
    font-size: 12px; min-height: 18px; }}
QPushButton[role="link"]:hover {{ text-decoration: underline; }}
QPushButton[role="link"]:disabled {{ color: {c.muted}; }}
QPushButton[role="link"]:focus {{ border: 1px solid {c.accent}; }}
QPushButton[role="filter"] {{ border-radius: 15px; min-height: 18px; padding: 5px 14px; font-size: 13px; }}
QPushButton[role="filter"]:checked {{ background: {c.accent}; color: {c.accent_text}; border: 0; font-weight: 600; }}

QFrame#DoneCard {{ background: {c.note}; border-radius: 10px; }}
QLabel#DoneText {{ color: {c.text}; font-weight: 600; }}
QFrame#DropZone {{ background: {c.drop}; border: 2px dashed {c.drop_border}; border-radius: 10px; }}
QFrame#DropZone[active="true"] {{ border-color: {c.accent}; background: {c.accent_soft}; }}
QFrame[role="card"] {{ background: {c.surface}; border: 1px solid {c.border}; border-radius: 8px; }}
QFrame[role="card"] QLabel {{ border: 0; }}
QFrame#Divider {{ background: {c.border}; max-height: 1px; min-height: 1px; border: 0; }}

QLineEdit, QComboBox {{ background: {c.surface}; border: 1px solid {c.border_strong}; border-radius: 8px;
    padding: 7px 10px; selection-background-color: {c.accent}; selection-color: {c.accent_text}; }}
QLineEdit:focus, QComboBox:focus {{ border: 2px solid {c.accent}; padding: 6px 9px; }}

QCheckBox, QRadioButton {{ spacing: 10px; }}
QCheckBox::indicator, QRadioButton::indicator {{ width: 16px; height: 16px; background: {c.surface};
    border: 2px solid {c.muted}; }}
QCheckBox::indicator {{ border-radius: 4px; }}
QCheckBox::indicator:checked {{ background: {c.accent}; border-color: {c.accent}; image: url("{check_image}"); }}
QRadioButton::indicator {{ border-radius: 10px; }}
QRadioButton::indicator:checked {{ border: 6px solid {c.accent}; width: 8px; height: 8px; }}
QCheckBox::indicator:disabled, QRadioButton::indicator:disabled {{ border-color: {c.border_strong}; }}
QProgressBar {{ background: {c.border}; border: 0; border-radius: 2px; max-height: 4px; min-height: 4px; }}
QProgressBar::chunk {{ background: {c.accent}; border-radius: 2px; }}
QProgressBar[role="overall"] {{ max-height: 6px; min-height: 6px; border-radius: 3px; }}

QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {c.border_strong}; border-radius: 3px; min-height: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

QMenu {{ background: {c.surface}; border: 1px solid {c.border_strong}; padding: 4px; }}
QMenu::item {{ padding: 6px 16px; border-radius: 4px; }}
QMenu::item:selected {{ background: {c.accent_soft}; color: {c.accent_soft_text}; }}
QMenu::item:disabled {{ color: {c.muted}; }}
QListWidget {{ background: {c.surface}; border: 1px solid {c.border}; border-radius: 8px; padding: 4px;
    outline: 0; }}
QListWidget::item {{ padding: 8px 10px; border-radius: 6px; color: {c.text}; }}
QListWidget::item:hover {{ background: {c.hover}; }}
QListWidget::item:selected {{ background: {c.accent_soft}; color: {c.accent_soft_text}; }}
QListWidget[role="pages"]::item {{ padding: 6px; }}
QTreeWidget {{ background: {c.surface}; border: 1px solid {c.border}; border-radius: 8px; }}
QHeaderView::section {{ background: {c.note}; border: 0; padding: 6px; }}
"""


def repolish(widget: QWidget) -> None:
    """Re-apply the stylesheet after a property such as ``state`` changed."""
    widget.style().unpolish(widget)
    widget.style().polish(widget)


class ThemeManager(QObject):
    """Applies the chosen look to the whole app and follows Windows if asked to."""

    changed = Signal(object)  # Colors

    def __init__(self, app: QApplication, choice: str = SYSTEM) -> None:
        super().__init__(app)
        self.app = app
        self.choice = choice if choice in (SYSTEM, LIGHT, DARK) else SYSTEM
        self.colors = LIGHT_COLORS
        self._applying = False
        app.setStyle("Fusion")  # draws the same everywhere; colours come from below
        app.styleHints().colorSchemeChanged.connect(self._system_changed)
        self.apply()

    def set_choice(self, choice: str) -> None:
        if choice not in (SYSTEM, LIGHT, DARK):
            raise ValueError(f"unknown theme: {choice}")
        self.choice = choice
        self.apply()

    def system_mode(self) -> str:
        return DARK if self.app.styleHints().colorScheme() == Qt.ColorScheme.Dark else LIGHT

    def apply(self) -> None:
        self._applying = True
        try:
            hints = self.app.styleHints()
            # Telling Qt the colour scheme also gives the window a matching (dark) title bar.
            if self.choice == SYSTEM:
                hints.unsetColorScheme()
                mode = self.system_mode()
            else:
                hints.setColorScheme(
                    Qt.ColorScheme.Dark if self.choice == DARK else Qt.ColorScheme.Light
                )
                mode = self.choice
            self.colors = colors_for(mode)
            self.app.setPalette(palette(self.colors))
            self.app.setStyleSheet(stylesheet(self.colors))
        finally:
            self._applying = False
        self.changed.emit(self.colors)

    def _system_changed(self, *_args) -> None:
        if not self._applying and self.choice == SYSTEM and self.system_mode() != self.colors.mode:
            self.apply()


def manager(app: QApplication | None = None, choice: str | None = None) -> ThemeManager:
    """The app's one ThemeManager (created on first use)."""
    app = app or QApplication.instance()
    existing = app.findChild(ThemeManager)
    if existing is None:
        return ThemeManager(app, choice or SYSTEM)
    if choice is not None and choice != existing.choice:
        existing.set_choice(choice)
    return existing
