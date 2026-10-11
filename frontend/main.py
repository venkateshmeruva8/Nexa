"""NEXA Frontend Main Entrypoint.

Initializes QGuiApplication, registers NexaUIController,
configures QML engine, and starts the event loop.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine

from frontend.controller import NexaUIController


def main() -> int:
    base_dir = Path(__file__).resolve().parent

    # Enable High DPI scaling
    os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "1"
    os.environ["QT_AUTO_SCREEN_SCALE_FACTOR"] = "1"

    app = QGuiApplication(sys.argv)
    app.setApplicationName("NEXA Voice Assistant")
    app.setOrganizationName("NEXA")

    controller = NexaUIController()
    app.aboutToQuit.connect(controller.shutdown)

    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("controller", controller)
    engine.rootContext().setContextProperty("nexaController", controller)

    qml_file = base_dir / "qml" / "Main.qml"
    engine.load(QUrl.fromLocalFile(str(qml_file)))

    if not engine.rootObjects():
        print("[ERROR] Failed to load QML root object.")
        return 1

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
