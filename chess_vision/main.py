import sys
from pathlib import Path
from PyQt5.QtWidgets import QApplication
from ui.main_window import MainWindow


def main() -> None:
    app    = QApplication(sys.argv)
    app.setApplicationName("CV Chess")
    app.setStyle("Fusion")

    # Dark palette
    from PyQt5.QtGui import QPalette, QColor
    from PyQt5.QtCore import Qt
    palette = QPalette()
    palette.setColor(QPalette.Window,          QColor(30,  30,  30))
    palette.setColor(QPalette.WindowText,      QColor(220, 220, 220))
    palette.setColor(QPalette.Base,            QColor(20,  20,  20))
    palette.setColor(QPalette.AlternateBase,   QColor(40,  40,  40))
    palette.setColor(QPalette.ToolTipBase,     QColor(220, 220, 220))
    palette.setColor(QPalette.ToolTipText,     QColor(220, 220, 220))
    palette.setColor(QPalette.Text,            QColor(220, 220, 220))
    palette.setColor(QPalette.Button,          QColor(53,  53,  53))
    palette.setColor(QPalette.ButtonText,      QColor(220, 220, 220))
    palette.setColor(QPalette.BrightText,      QColor(255, 50,  50))
    palette.setColor(QPalette.Link,            QColor(42,  130, 218))
    palette.setColor(QPalette.Highlight,       QColor(42,  130, 218))
    palette.setColor(QPalette.HighlightedText, QColor(0,   0,   0))
    app.setPalette(palette)

    window = MainWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
