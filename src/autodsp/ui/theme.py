COLORS = {
    "bg": "#0f131a",
    "panel": "#171c26",
    "panel2": "#1e2430",
    "border": "#2a3242",
    "text": "#e6eaf2",
    "muted": "#8b95a7",
    "cyan": "#22d3ee",
    "green": "#34d399",
    "orange": "#fb923c",
    "red": "#ef4444",
}


def stylesheet() -> str:
    c = COLORS
    return f"""
    QWidget {{ background: {c['bg']}; color: {c['text']}; font-size: 13px; }}
    QMainWindow, QDialog {{ background: {c['bg']}; }}
    QGroupBox {{ background: {c['panel']}; border: 1px solid {c['border']};
                 border-radius: 8px; margin-top: 14px; padding: 10px; }}
    QGroupBox::title {{ subcontrol-origin: margin; left: 12px; padding: 0 6px;
                        color: {c['cyan']}; font-weight: 600; background: transparent; }}
    QLabel {{ background: transparent; }}
    QPushButton {{ background: {c['panel2']}; border: 1px solid {c['border']};
                   border-radius: 6px; padding: 7px 14px; }}
    QPushButton:hover {{ border-color: {c['cyan']}; }}
    QPushButton:pressed {{ background: {c['border']}; }}
    QPushButton:disabled {{ color: {c['muted']}; }}
    QPushButton#emergency {{ background: {c['red']}; color: white; font-weight: 700;
                             font-size: 15px; padding: 10px 22px; border: none; }}
    QPushButton#emergency:hover {{ background: #f87171; }}
    QPushButton#arm {{ background: {c['panel2']}; border: 2px solid {c['orange']}; font-weight: 600; }}
    QPushButton#arm[armed="true"] {{ border-color: {c['green']}; color: {c['green']}; }}
    QTabWidget::pane {{ border: 1px solid {c['border']}; border-radius: 6px; top: -1px; }}
    QTabBar::tab {{ background: {c['panel']}; padding: 9px 20px; border: 1px solid {c['border']};
                    border-bottom: none; border-top-left-radius: 6px; border-top-right-radius: 6px;
                    margin-right: 2px; color: {c['muted']}; }}
    QTabBar::tab:selected {{ color: {c['cyan']}; background: {c['panel2']}; }}
    QSlider::groove:horizontal {{ height: 6px; background: {c['border']}; border-radius: 3px; }}
    QSlider::sub-page:horizontal {{ background: {c['cyan']}; border-radius: 3px; }}
    QSlider::handle:horizontal {{ background: {c['text']}; width: 18px; margin: -7px 0;
                                  border-radius: 9px; }}
    QDoubleSpinBox, QSpinBox, QComboBox, QLineEdit {{
        background: {c['panel2']}; border: 1px solid {c['border']}; border-radius: 5px; padding: 4px 6px; }}
    QDoubleSpinBox:focus, QComboBox:focus, QLineEdit:focus {{ border-color: {c['cyan']}; }}
    QTableWidget {{ background: {c['panel']}; gridline-color: {c['border']}; border: none; }}
    QHeaderView::section {{ background: {c['panel2']}; color: {c['muted']}; border: none; padding: 6px; }}
    QListWidget {{ background: {c['panel']}; border: 1px solid {c['border']}; border-radius: 6px; }}
    QListWidget::item:selected {{ background: {c['panel2']}; color: {c['cyan']}; }}
    QStatusBar {{ background: {c['panel']}; color: {c['muted']}; }}
    QCheckBox {{ background: transparent; spacing: 8px; }}
    """
