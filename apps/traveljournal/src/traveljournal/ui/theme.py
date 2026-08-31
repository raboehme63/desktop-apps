"""Visual theme for a modern Windows desktop look."""

from __future__ import annotations

from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication

STYLESHEET = """
QWidget {
    background-color: #12151c;
    color: #e8edf5;
    font-family: "Segoe UI Variable", "Segoe UI", sans-serif;
    font-size: 13px;
}

QMainWindow, QDialog {
    background-color: #12151c;
}

#sidebar {
    background-color: #181c27;
    border-right: 1px solid #2a3144;
}

QPushButton {
    background-color: #243044;
    border: 1px solid #33415c;
    border-radius: 8px;
    padding: 8px 14px;
    color: #e8edf5;
}

QPushButton:hover {
    background-color: #2c3a52;
}

QPushButton:pressed {
    background-color: #1c2738;
}

QPushButton:disabled {
    color: #6b7385;
    background-color: #1a2030;
}

QPushButton#entryToMap,
QPushButton#entryMenuButton {
    padding: 4px 10px;
    font-size: 12px;
}

QCheckBox#entryHide {
    min-width: 46px;
    max-width: 46px;
    min-height: 24px;
    max-height: 24px;
    padding: 0px;
    spacing: 0px;
    background: transparent;
    border: none;
}

QCheckBox#entryHide::indicator {
    width: 0px;
    height: 0px;
    border: none;
}

QPushButton#primary {
    background-color: #2eb8a0;
    border: 1px solid #2eb8a0;
    color: #06231e;
    font-weight: 600;
}

QPushButton#primary:hover {
    background-color: #3ccbb2;
}

QPushButton#primary:disabled,
QPushButton#primary:disabled:hover {
    background-color: #1a2030;
    border: 1px solid #2a3144;
    color: #6b7385;
}

QPushButton#exportChoice,
QPushButton#exportQualityChoice {
    min-width: 108px;
    padding: 10px 14px;
    text-align: center;
}

QPushButton#exportChoice:checked,
QPushButton#exportQualityChoice:checked {
    background-color: #243b3a;
    border: 1px solid #2eb8a0;
    color: #7eebcf;
    font-weight: 600;
}

QPushButton#exportChoice:checked:hover,
QPushButton#exportQualityChoice:checked:hover {
    background-color: #2a4744;
}

QPushButton#exportChoice:disabled,
QPushButton#exportQualityChoice:disabled {
    color: #6b7385;
    background-color: #1a2030;
}

QPushButton#exportLayoutChoice {
    background-color: #1f2636;
    border: 1px solid #343e55;
    border-radius: 8px;
    color: #d7ddea;
    font-size: 11px;
    min-width: 56px;
    max-width: 80px;
    padding: 6px 4px 8px 4px;
    text-align: center;
}

QPushButton#exportLayoutChoice:hover {
    background-color: #273044;
    border: 1px solid #4b5875;
}

QPushButton#exportLayoutChoice:checked {
    background-color: #243b3a;
    border: 1px solid #2eb8a0;
    color: #7eebcf;
    font-weight: 600;
}

QPushButton#exportLayoutChoice:checked:hover {
    background-color: #2a4744;
}

QPushButton#exportLayoutChoice:disabled {
    color: #6b7385;
    background-color: #1a2030;
}

QWidget#bookStage {
    background-color: #152038;
    border-radius: 12px;
}

QFrame#bookPage,
QFrame#bookPage QStackedWidget,
QFrame#bookPage QStackedWidget > QWidget {
    background-color: #f7f4ee;
    color: #1a2744;
    border-radius: 2px;
}

QFrame#bookPage QLabel {
    background-color: transparent;
    color: #1a2744;
}

QLabel#bookCenteredTitle {
    font-size: 28px;
    font-weight: 600;
    color: #1a2744;
    background-color: #f7f4ee;
}

QFrame#bookCountries {
    background-color: #1a2744;
    color: #f4f7fb;
}

QFrame#bookPage QFrame#bookCountries,
QFrame#bookPage QFrame#bookCountries QWidget {
    background-color: #1a2744;
    color: #f4f7fb;
}

QFrame#bookPage QFrame#bookCountries QLabel {
    background-color: #1a2744;
    color: #f4f7fb;
}

QLabel#bookCountriesKicker {
    font-size: 11px;
    letter-spacing: 0.14em;
    color: #9ec9b8;
}

QLabel#bookCountriesList {
    font-size: 16px;
    font-weight: 600;
}

QWidget#bookCountryItem,
QWidget#bookCountryMark {
    background-color: #1a2744;
}

QLabel#bookCountryName {
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.08em;
    color: #f4f7fb;
}

QWidget#bookSectionLocator {
    background-color: #f7f4ee;
}

QLabel#bookSectionCountry {
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.12em;
}

QLabel#bookSectionTitle {
    font-size: 20px;
    font-weight: 700;
    letter-spacing: 0.04em;
}

QLabel#bookSectionKind {
    color: #5c6b7a;
}

QLabel#bookSectionNotes {
    font-size: 12px;
}

QFrame#bookNotesBox {
    background-color: #e4dfd6;
    border: none;
}

QFrame#bookPage QLabel#bookSectionCover {
    background-color: #f7f4ee;
    border: none;
}

QWidget#bookTripSpan {
    background-color: #f7f4ee;
}

QScrollArea#countryList {
    background-color: #1c2230;
    border: 1px solid #2a3144;
    border-radius: 8px;
}

QWidget#countryListInner,
QWidget#countryRow {
    background-color: #1c2230;
}

QLabel#countryRowName {
    font-weight: 600;
}

QPushButton#countryAdd {
    padding: 8px 12px;
}

QPushButton#countryRemove {
    padding: 4px 10px;
    min-width: 0;
}

QFrame#bookMetrics,
QFrame#bookPage QFrame#bookMetrics,
QFrame#bookPage QFrame#bookMetrics QWidget {
    background-color: #f7f4ee;
    color: #1a2744;
}

QFrame#bookPage QFrame#bookMetrics QLabel {
    background-color: #f7f4ee;
    color: #1a2744;
}

QLabel#bookMetricsHeading {
    font-size: 11px;
    letter-spacing: 0.14em;
    color: #5c6b7a;
}

QLabel#bookMetricValue {
    font-size: 28px;
    font-weight: 600;
    color: #1a2744;
}

QLabel#bookMetricCaption {
    font-size: 12px;
    color: #5c6b7a;
}

QLabel#bookPageTitle {
    font-size: 18px;
    font-weight: 600;
}

QLabel#bookKicker {
    font-size: 11px;
    letter-spacing: 0.08em;
    color: #5c6b7a;
}

QFrame#bookCover {
    background-color: #1a2744;
    border-radius: 2px;
    color: #f4f7fb;
}

QFrame#bookCover QStackedWidget,
QFrame#bookCover QStackedWidget > QWidget {
    background-color: #1a2744;
    color: #f4f7fb;
}

QFrame#bookCover QLabel {
    background: transparent;
    color: #f4f7fb;
}

QFrame#bookCover QLabel#bookKicker {
    color: #9ec9b8;
    letter-spacing: 0.12em;
}

QLabel#bookImage {
    background-color: #d9d3c7;
    border-radius: 2px;
}

QFrame#bookCover QLabel#bookImage {
    background-color: #12151c;
}

QLabel#bookIndicator {
    color: #e8edf5;
    font-weight: 600;
}

QPushButton#bookFlip {
    min-width: 44px;
    max-width: 44px;
    padding: 0;
    font-size: 22px;
}

QPushButton#exportManageTemplates {
    padding: 6px 10px;
    font-size: 12px;
    min-width: 0;
}

QPushButton#bookNav {
    min-width: 44px;
    max-width: 44px;
    padding: 8px 0;
}

#timelinePool {
    background-color: #181c27;
    border-left: 1px solid #2a3144;
}

#mapEntrySide QPushButton {
    padding: 6px 8px;
    font-size: 12px;
}

QPushButton#sidebarButton {
    text-align: left;
    border: none;
    border-radius: 10px;
    min-width: 0;
    padding: 10px 12px 10px 10px;
    background-color: transparent;
    color: #c5cddb;
}

QPushButton#sidebarButton:hover {
    background-color: #23293a;
}

QPushButton#sidebarButton:checked {
    background-color: #243b3a;
    color: #7eebcf;
    font-weight: 600;
}

QPushButton#sidebarCollapse,
QPushButton#poolCollapse {
    min-width: 14px;
    max-width: 14px;
    min-height: 56px;
    padding: 8px 0;
    border: 1px solid #3d4a66;
    border-right: none;
    border-radius: 8px 0 0 8px;
    background-color: #243044;
    color: #e8edf5;
}

QPushButton#sidebarCollapse:hover,
QPushButton#poolCollapse:hover {
    background-color: #33415c;
    border-color: #5b6b8a;
}

#sidebar[collapsed="true"] QPushButton#sidebarButton {
    text-align: center;
    min-width: 32px;
    padding: 10px 8px;
}

QLineEdit, QPlainTextEdit, QTextEdit {
    background-color: #1c2230;
    border: 1px solid #2a3144;
    border-radius: 8px;
    padding: 8px 10px;
    selection-background-color: #2eb8a0;
    selection-color: #06231e;
}

QLineEdit#tripTitleEdit {
    font-size: 18px;
    font-weight: 600;
    padding: 10px 12px;
}

QTableWidget {
    background-color: #171b26;
    alternate-background-color: #1c2230;
    gridline-color: #2a3144;
    border: 1px solid #2a3144;
    border-radius: 10px;
}

QHeaderView::section {
    background-color: #1c2230;
    color: #8b95a8;
    border: none;
    padding: 8px;
    font-weight: 600;
}

QProgressBar {
    background-color: #1c2230;
    border: 1px solid #2a3144;
    border-radius: 8px;
    text-align: center;
    color: #e8edf5;
    height: 18px;
}

QProgressBar::chunk {
    background-color: #2eb8a0;
    border-radius: 7px;
}

QComboBox, QDateEdit, QSpinBox {
    background-color: #1c2230;
    border: 1px solid #2a3144;
    border-radius: 8px;
    padding: 6px 10px;
    color: #e8edf5;
}

QDateEdit {
    min-width: 168px;
}

QComboBox::drop-down,
QDateEdit::drop-down {
    border: none;
    width: 22px;
}

QCheckBox {
    color: #c5cddb;
    spacing: 8px;
}

QListView {
    background-color: #12151c;
    border: 1px solid #2a3144;
    border-radius: 10px;
    outline: none;
}

QLabel#pageTitle {
    font-size: 22px;
    font-weight: 600;
    color: #f4f7fb;
}

QLabel#pageSubtitle {
    color: #8b95a8;
}

QLabel#youtubeThumb {
    background-color: #1c2230;
    border: 1px solid #2a3144;
    border-radius: 8px;
}

QWidget#mapFrame {
    background-color: #12151c;
}

QWidget#mapYoutubeOverlay {
    background-color: transparent;
}

QWidget#mapTimelineOverlay {
    background-color: transparent;
}

QWidget#mapTimelineOverlay > QWidget,
QScrollArea#mapTimelineStrip,
QScrollArea#mapTimelineStrip QWidget {
    background-color: transparent;
    border: none;
}

QFrame#mapTimelineCard {
    background: transparent;
    border: none;
}

QFrame#mapTimelineCard[focused="true"] {
    border: none;
}

QWidget#timelineJoin {
    background-color: #12151c;
    border: none;
}

QWidget#mapTimelineJoin,
QWidget#joinPlus {
    background-color: transparent;
    border: none;
}

QFrame#card {
    background-color: #3a4860;
    border: 1px solid #8fa0bb;
    border-radius: 12px;
}

QFrame#card[tripHidden="true"] {
    background-color: #252a38;
    border: 1px dashed #6b7385;
}

QFrame#card[tripHidden="true"] QLabel#entryDates,
QFrame#card[tripHidden="true"] QLabel#fieldCaption,
QFrame#card[tripHidden="true"] QLabel#entryExtra {
    color: #8b95a8;
}

QFrame#card QLabel {
    background-color: transparent;
}

QFrame#card QLabel#entryCover {
    background-color: #12151c;
    border: 1px solid #2a3144;
    border-radius: 8px;
}

QFrame#card QLabel#youtubeThumb {
    background-color: #1c2230;
    border: 1px solid #2a3144;
    border-radius: 8px;
}

QLabel#entryDates {
    background-color: transparent;
    color: #f4f7fb;
    font-size: 16px;
    font-weight: 600;
}

QLabel#entryExtra {
    background-color: transparent;
    color: #c5cddb;
    font-size: 12px;
}

QLabel#fieldCaption {
    background-color: transparent;
    color: #e8edf5;
    font-size: 14px;
    font-weight: 600;
}

QComboBox#sectionKind {
    min-width: 108px;
    max-width: 148px;
    padding: 4px 8px;
}

QComboBox#sectionKind QAbstractItemView {
    min-height: 96px;
    background-color: #1c2230;
    selection-background-color: #243b3a;
}

QComboBox#sectionKind QAbstractItemView::item {
    min-height: 28px;
    padding: 4px 10px;
}

QFrame#card[dropTarget="true"],
QFrame#timelinePool[dropTarget="true"] {
    border: 1px solid #2eb8a0;
}

QLabel#statValue {
    font-size: 22px;
    font-weight: 600;
    color: #7eebcf;
}

QLabel#statLabel {
    color: #8b95a8;
}

QStatusBar {
    background-color: #181c27;
    color: #8b95a8;
    border-top: 1px solid #2a3144;
}

QMenuBar {
    background-color: #181c27;
    color: #e8edf5;
    border-bottom: 1px solid #2a3144;
    padding: 4px 8px;
}

QMenuBar::item {
    background: transparent;
    padding: 4px 10px;
    border-radius: 6px;
}

QMenuBar::item:selected {
    background-color: #243044;
}

QMenu {
    background-color: #1a2030;
    color: #e8edf5;
    border: 1px solid #2a3144;
    padding: 6px;
}

QMenu::item {
    padding: 6px 18px;
    border-radius: 6px;
}

QMenu::item:selected {
    background-color: #243b3a;
    color: #7eebcf;
}

QMenu::separator {
    height: 1px;
    background: #2a3144;
    margin: 4px 8px;
}

#mediaFilterPanel {
    background-color: #181c27;
    border: 1px solid #2a3144;
    border-radius: 10px;
    padding: 8px;
}

#mediaFilterPanel QGroupBox {
    border: 1px solid #2a3144;
    border-radius: 8px;
    margin-top: 10px;
    padding: 10px 8px 8px 8px;
    font-weight: 600;
}

#mediaFilterPanel QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 4px;
    color: #c5cddb;
}

QPushButton#mediaFilterButton:checked {
    border-color: #2eb8a0;
}

QToolButton#entryMenu {
    background: transparent;
    border: none;
    font-size: 18px;
    padding: 2px 8px;
    min-width: 28px;
}

QToolButton#entryMenu:hover {
    background-color: #243044;
    border-radius: 8px;
}

QToolButton#entryMenu::menu-indicator {
    image: none;
}

QSlider#thumbZoomSlider {
    min-height: 22px;
}

QSlider#thumbZoomSlider::groove:horizontal {
    height: 4px;
    background: #2a3144;
    border-radius: 2px;
}

QSlider#thumbZoomSlider::handle:horizontal {
    width: 18px;
    height: 18px;
    margin: -7px 0;
    background: transparent;
    border: none;
}

QTabBar#mediaSortTabs {
    background: transparent;
}

QTabBar#mediaSortTabs::tab {
    background-color: #1a2030;
    color: #9aa6b8;
    border: 1px solid #2a3144;
    border-bottom: none;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
    padding: 6px 14px;
    margin-right: 4px;
}

QTabBar#mediaSortTabs::tab:selected {
    background-color: #243044;
    color: #f4f7fb;
}

QTabBar#mediaSortTabs::tab:hover {
    color: #e8edf5;
}

QPushButton#ratingChip,
QPushButton#inspectorToMap {
    min-width: 108px;
}

QPushButton#ratingChip:checked {
    font-weight: 600;
    border-color: #2eb8a0;
    color: #7eebcf;
}

QPushButton#rotateChip {
    min-width: 44px;
    font-size: 16px;
}

QGroupBox {
    background-color: #1a2030;
    border: 1px solid #2a3144;
    border-radius: 12px;
    margin-top: 12px;
    padding: 12px 12px 8px 12px;
    font-weight: 600;
}

QGroupBox::title {
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 6px;
    color: #f4f7fb;
}

QLabel#timelineScrollDate {
    background-color: #2eb8a0;
    color: #06231e;
    border-radius: 8px;
    padding: 4px 10px;
    font-weight: 600;
    font-size: 12px;
}

QScrollArea {
    border: none;
}
"""


def apply_theme(app: QApplication) -> None:
    app.setStyle("Fusion")
    font = QFont("Segoe UI", 10)
    app.setFont(font)
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor("#12151c"))
    palette.setColor(QPalette.ColorRole.WindowText, QColor("#e8edf5"))
    palette.setColor(QPalette.ColorRole.Base, QColor("#1c2230"))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor("#171b26"))
    palette.setColor(QPalette.ColorRole.Text, QColor("#e8edf5"))
    palette.setColor(QPalette.ColorRole.Button, QColor("#243044"))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor("#e8edf5"))
    palette.setColor(QPalette.ColorRole.Highlight, QColor("#2eb8a0"))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#06231e"))
    app.setPalette(palette)
    app.setStyleSheet(STYLESHEET)
