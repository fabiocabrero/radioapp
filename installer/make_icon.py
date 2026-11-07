"""Gera installer/ic7300.ico (círculo escuro com '73' verde) usando o próprio Qt."""
import sys
from pathlib import Path

from PySide6 import QtCore, QtGui

app = QtGui.QGuiApplication(sys.argv)
img = QtGui.QImage(256, 256, QtGui.QImage.Format.Format_ARGB32)
img.fill(QtCore.Qt.GlobalColor.transparent)
p = QtGui.QPainter(img)
p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
p.setBrush(QtGui.QColor("#10151c"))
p.setPen(QtGui.QPen(QtGui.QColor("#2e7d32"), 10))
p.drawEllipse(10, 10, 236, 236)
p.setPen(QtGui.QColor("#7CFC9A"))
p.setFont(QtGui.QFont("Consolas", 96, QtGui.QFont.Weight.Bold))
p.drawText(QtCore.QRect(0, 0, 256, 256), QtCore.Qt.AlignmentFlag.AlignCenter, "73")
p.end()
out = Path(__file__).parent / "ic7300.ico"
print("ico:", img.save(str(out)), out)
