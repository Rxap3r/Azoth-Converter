"""The "Supported formats" page: every format and what it converts into."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from .. import metadata, ranking
from ..converters import msword, office
from ..format_list import CATEGORY_TITLES, conversion_table
from .targets import display_name
from .widgets import download_button, flow_container, label

LIBREOFFICE_TIP = "Needs LibreOffice, a free program from libreoffice.org"


def _chip(text: str, *, libreoffice: bool = False, clean: bool = False) -> QLabel:
    chip = QLabel(text)
    chip.setProperty("role", "chip")
    chip.setProperty("libreoffice", "true" if libreoffice else "false")
    chip.setProperty("clean", "true" if clean else "false")
    if libreoffice:
        chip.setToolTip(LIBREOFFICE_TIP)
    return chip


class FormatRow(QFrame):
    def __init__(self, row, libreoffice_installed: bool, can_convert=None) -> None:
        super().__init__()
        fmt = row.format
        self.format_id = fmt.id
        self.category = fmt.category
        self.setProperty("role", "card")
        # Searchable text: id, name, extensions and all targets.
        self.haystack = " ".join(
            [fmt.id, fmt.name, *fmt.extensions]
            + [t.id for t in row.right_away + row.needs_libreoffice]
        ).lower()

        badge = QLabel(display_name(fmt.id))
        badge.setProperty("role", "badge")
        badge.setProperty("category", fmt.category)
        badge.setFixedSize(52, 28)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        names = QVBoxLayout()
        names.setSpacing(0)
        name = label(fmt.name)
        name.setStyleSheet("font-weight: 600; font-size: 13px;")
        name.setWordWrap(True)
        names.addWidget(name)
        names.addWidget(label("  ".join(f".{e}" for e in fmt.extensions), "small"))
        left = QHBoxLayout()
        left.setSpacing(12)
        left.addWidget(badge, 0, Qt.AlignmentFlag.AlignTop)
        left.addLayout(names, 1)
        left_box = QWidget()
        left_box.setLayout(left)
        left_box.setFixedWidth(230)

        chips, flow = flow_container()
        ordered = ranking.rank(row.right_away + row.needs_libreoffice, [fmt.category])
        needs = {t.id for t in row.needs_libreoffice}
        for target in ordered:
            flow.addWidget(
                _chip(
                    display_name(target.id),
                    libreoffice=target.id in needs
                    and not libreoffice_installed
                    and not (can_convert and can_convert(fmt.id, target.id)),
                )
            )
        if fmt.id in metadata.CLEANABLE:
            flow.addWidget(_chip("Remove metadata", clean=True))
        if not ordered:
            flow.addWidget(label("Nothing yet", "small"))

        self.arrow = QLabel("→")
        self.arrow.setProperty("role", "muted")
        self.arrow.setAccessibleName("converts to")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(16)
        layout.addWidget(left_box, 0, Qt.AlignmentFlag.AlignTop)
        layout.addWidget(self.arrow, 0, Qt.AlignmentFlag.AlignTop)
        layout.addWidget(chips, 1)


class FormatsPanel(QWidget):
    def __init__(self, libreoffice_installed: bool, can_convert=None) -> None:
        """``can_convert(src, dst)``: True if an installed engine (e.g. Microsoft Office)
        does the conversion, so it isn't shown as needing LibreOffice."""
        super().__init__()
        self._category: str | None = None
        office_apps = [a.short for a in msword.office_installed()] if can_convert else []

        if libreoffice_installed:
            status = ""  # nothing to do: no message
        elif office_apps:
            status = (
                f"Microsoft {', '.join(office_apps)} does the office conversions it can. "
                "Those with a dashed outline need LibreOffice (free download from libreoffice.org)."
            )
        else:
            status = (
                "LibreOffice isn't installed. Conversions with a dashed outline need it "
                "(free download from libreoffice.org)."
            )
        self.status_label = label(status, "muted", wrap=True)
        self.download_btn = None
        if not libreoffice_installed:
            self.download_btn = download_button("Download LibreOffice…", office.DOWNLOAD_URL)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Search, e.g. heic or .docx")
        self.search.setClearButtonEnabled(True)
        self.search.setAccessibleName("Search formats")
        self.search.setFixedWidth(300)
        self.search.textChanged.connect(self.apply_filter)

        heading = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(2)
        titles.addWidget(label("Supported formats", "h1"))
        titles.addWidget(label("Find a file type to see what it can become.", "muted", wrap=True))
        heading.addLayout(titles, 1)
        heading.addWidget(self.search, 0, Qt.AlignmentFlag.AlignBottom)

        filters = QHBoxLayout()
        filters.setSpacing(8)
        self.filter_group = QButtonGroup(self)
        self.filter_buttons: dict[str | None, QPushButton] = {}
        for key, title in [(None, "All"), *CATEGORY_TITLES.items()]:
            button = QPushButton(title)
            button.setProperty("role", "filter")
            button.setCheckable(True)
            button.setChecked(key is None)
            button.clicked.connect(lambda _=False, k=key: self.set_category(k))
            self.filter_group.addButton(button)
            self.filter_buttons[key] = button
            filters.addWidget(button)
        filters.addStretch(1)
        if not libreoffice_installed:
            legend = _chip("Dashed", libreoffice=True)
            filters.addWidget(legend)
            filters.addWidget(label("needs LibreOffice (free)", "small"))

        column = QWidget()
        rows_layout = QVBoxLayout(column)
        rows_layout.setContentsMargins(0, 0, 4, 0)
        rows_layout.setSpacing(6)
        self.rows: list[FormatRow] = []
        for row in conversion_table():
            widget = FormatRow(row, libreoffice_installed, can_convert)
            self.rows.append(widget)
            rows_layout.addWidget(widget)
        self.no_match = label("No format matches your search.", "muted")
        self.no_match.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.no_match.setVisible(False)
        rows_layout.addWidget(self.no_match)
        rows_layout.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(column)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 20)
        layout.setSpacing(14)
        layout.addLayout(heading)
        if status:
            layout.addWidget(self.status_label)
        if self.download_btn is not None:
            layout.addWidget(self.download_btn, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addLayout(filters)
        layout.addWidget(scroll, 1)

    def set_category(self, category: str | None) -> None:
        self._category = category
        self.filter_buttons[category].setChecked(True)
        self.apply_filter(self.search.text())

    def apply_filter(self, text: str | None = None) -> None:
        """Show only formats of the chosen kind whose name, extension or targets match."""
        words = (self.search.text() if text is None else text).lower().split()
        shown = 0
        for row in self.rows:
            match = (self._category is None or row.category == self._category) and all(
                w.lstrip(".") in row.haystack for w in words
            )
            row.setVisible(match)
            shown += match
        self.no_match.setVisible(shown == 0)

    def visible_formats(self) -> list[str]:
        """Format ids currently shown (used by tests)."""
        return [row.format_id for row in self.rows if not row.isHidden()]
