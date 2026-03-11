#!/usr/bin/env python3
"""
Advanced Color Picker Dialog with HSV/RGB sliders, hex input, color wheel,
recent colors, and cross-config palette support.
"""

import colorsys
import math
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QSlider, QPushButton, QWidget, QLineEdit,
    QTabWidget, QGroupBox
)
from PyQt6.QtCore import Qt, pyqtSignal, QSettings, QPointF, QRectF, QRegularExpression
from PyQt6.QtGui import (
    QColor, QPainter, QConicalGradient,
    QLinearGradient, QImage, QPen, QBrush,
    QRegularExpressionValidator
)


class ColorWheelWidget(QWidget):
    """HSV color wheel: hue ring + saturation/value square"""

    color_changed = pyqtSignal(int, int, int)  # h, s, v

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(220, 220)
        self.setMaximumSize(220, 220)
        self._hue = 0
        self._sat = 255
        self._val = 255
        self._ring_width = 22
        self._dragging_ring = False
        self._dragging_square = False
        self._wheel_image = None

    def set_color(self, h, s, v):
        """Set color without emitting signal"""
        self._hue = h
        self._sat = s
        self._val = v
        self._wheel_image = None
        self.update()

    def _build_wheel_image(self):
        size = min(self.width(), self.height())
        img = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(Qt.GlobalColor.transparent)

        painter = QPainter(img)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        center = size / 2
        outer_r = center - 2
        inner_r = outer_r - self._ring_width

        gradient = QConicalGradient(center, center, 0)
        for i in range(13):
            angle = i / 12.0
            r, g, b = colorsys.hsv_to_rgb(angle, 1.0, 1.0)
            gradient.setColorAt(angle, QColor(int(r*255), int(g*255), int(b*255)))

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(gradient))
        painter.drawEllipse(QRectF(2, 2, outer_r*2, outer_r*2))

        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
        painter.drawEllipse(QRectF(center - inner_r, center - inner_r, inner_r*2, inner_r*2))
        painter.end()

        self._wheel_image = img

    def _get_sv_square_rect(self):
        size = min(self.width(), self.height())
        center = size / 2
        outer_r = center - 2
        inner_r = outer_r - self._ring_width
        half = inner_r / math.sqrt(2) - 4
        return QRectF(center - half, center - half, half * 2, half * 2)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        size = min(self.width(), self.height())
        center = size / 2
        outer_r = center - 2
        inner_r = outer_r - self._ring_width

        if self._wheel_image is None or self._wheel_image.size().width() != size:
            self._build_wheel_image()
        painter.drawImage(0, 0, self._wheel_image)

        # SV square
        sq = self._get_sv_square_rect()
        r, g, b = colorsys.hsv_to_rgb(self._hue / 360.0, 1.0, 1.0)
        base_color = QColor(int(r*255), int(g*255), int(b*255))

        sat_grad = QLinearGradient(sq.left(), sq.top(), sq.right(), sq.top())
        sat_grad.setColorAt(0, QColor(255, 255, 255))
        sat_grad.setColorAt(1, base_color)
        painter.fillRect(sq, sat_grad)

        val_grad = QLinearGradient(sq.left(), sq.top(), sq.left(), sq.bottom())
        val_grad.setColorAt(0, QColor(0, 0, 0, 0))
        val_grad.setColorAt(1, QColor(0, 0, 0, 255))
        painter.fillRect(sq, val_grad)

        # SV indicator
        sx = sq.left() + (self._sat / 255.0) * sq.width()
        sy = sq.top() + (1.0 - self._val / 255.0) * sq.height()
        painter.setPen(QPen(QColor(255, 255, 255), 2))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(QPointF(sx, sy), 5, 5)
        painter.setPen(QPen(QColor(0, 0, 0), 1))
        painter.drawEllipse(QPointF(sx, sy), 6, 6)

        # Hue indicator
        angle_rad = math.radians(self._hue)
        ring_r = (outer_r + inner_r) / 2
        hx = center + ring_r * math.cos(angle_rad)
        hy = center - ring_r * math.sin(angle_rad)
        painter.setPen(QPen(QColor(255, 255, 255), 2))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(QPointF(hx, hy), 6, 6)
        painter.setPen(QPen(QColor(0, 0, 0), 1))
        painter.drawEllipse(QPointF(hx, hy), 7, 7)

        painter.end()

    def mousePressEvent(self, event):
        self._handle_mouse(event, press=True)

    def mouseMoveEvent(self, event):
        self._handle_mouse(event, press=False)

    def mouseReleaseEvent(self, event):
        self._dragging_ring = False
        self._dragging_square = False

    def _handle_mouse(self, event, press=False):
        pos = event.position()
        size = min(self.width(), self.height())
        center = size / 2
        outer_r = center - 2
        inner_r = outer_r - self._ring_width
        dx = pos.x() - center
        dy = pos.y() - center
        dist = math.sqrt(dx*dx + dy*dy)

        sq = self._get_sv_square_rect()

        if press:
            if inner_r <= dist <= outer_r:
                self._dragging_ring = True
                self._dragging_square = False
            elif sq.contains(pos):
                self._dragging_square = True
                self._dragging_ring = False
            else:
                return

        if self._dragging_ring:
            angle = math.degrees(math.atan2(-dy, dx)) % 360
            self._hue = int(angle)
            self._wheel_image = None
            self.update()
            self.color_changed.emit(self._hue, self._sat, self._val)

        elif self._dragging_square:
            sx = max(0.0, min(1.0, (pos.x() - sq.left()) / sq.width()))
            sy = max(0.0, min(1.0, (pos.y() - sq.top()) / sq.height()))
            self._sat = int(sx * 255)
            self._val = int((1.0 - sy) * 255)
            self.update()
            self.color_changed.emit(self._hue, self._sat, self._val)


class HSVColorPicker(QDialog):
    """Advanced Color Picker with wheel, hex input, RGB/HSV sliders, recent colors, palette"""

    color_selected = pyqtSignal(int, int, int, int)

    MAX_RECENT = 12

    def __init__(self, parent=None, preset_index=0, initial_h=0, initial_s=255, initial_v=255,
                 palette_colors=None, config_colors=None):
        super().__init__(parent)
        self.setWindowTitle("Edit Colour")
        self.setMinimumWidth(520)
        self.setMinimumHeight(610)

        self.hsv_values = [initial_h, initial_s, initial_v]
        self.initial_hsv = (initial_h, initial_s, initial_v)
        self.preset_index = preset_index
        self.palette_colors = palette_colors or []
        self.config_colors = config_colors or []

        self._updating = False

        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout()
        layout.setSpacing(10)

        # ── Top: Color wheel + preview ──
        top_layout = QHBoxLayout()

        self.color_wheel = ColorWheelWidget()
        self.color_wheel.set_color(*self.hsv_values)
        self.color_wheel.color_changed.connect(self._on_wheel_changed)
        top_layout.addWidget(self.color_wheel)

        preview_layout = QVBoxLayout()
        preview_layout.addWidget(QLabel("Old"))
        self.old_preview = QWidget()
        self.old_preview.setFixedSize(80, 40)
        r, g, b = self._get_rgb()
        self.old_preview.setStyleSheet(
            f"background-color: rgb({r},{g},{b}); border: 1px solid #555; border-radius: 4px;"
        )
        preview_layout.addWidget(self.old_preview)

        preview_layout.addWidget(QLabel("New"))
        self.new_preview = QWidget()
        self.new_preview.setFixedSize(80, 40)
        self.new_preview.setStyleSheet(
            f"background-color: rgb({r},{g},{b}); border: 1px solid #555; border-radius: 4px;"
        )
        preview_layout.addWidget(self.new_preview)
        preview_layout.addStretch()
        top_layout.addLayout(preview_layout)

        layout.addLayout(top_layout)

        # ── Hex input ──
        hex_layout = QHBoxLayout()
        hex_layout.addWidget(QLabel("Hex:"))
        self.hex_input = QLineEdit()
        self.hex_input.setMaxLength(7)
        validator = QRegularExpressionValidator()
        validator.setRegularExpression(QRegularExpression("^#[0-9A-Fa-f]{0,6}$"))
        self.hex_input.setValidator(validator)
        self.hex_input.setPlaceholderText("#FF5500")
        self.hex_input.setFixedWidth(100)
        self.hex_input.editingFinished.connect(self._on_hex_changed)
        hex_layout.addWidget(self.hex_input)
        hex_layout.addStretch()
        layout.addLayout(hex_layout)

        # ── Sliders: HSV + RGB tabs ──
        tabs = QTabWidget()
        tabs.setMaximumHeight(180)

        # HSV tab
        hsv_widget = QWidget()
        hsv_lay = QVBoxLayout()
        hsv_lay.setSpacing(4)

        self.h_slider, self.h_label = self._make_slider("H", 0, 360, self.hsv_values[0], "°")
        self.s_slider, self.s_label = self._make_slider("S", 0, 255, self.hsv_values[1])
        self.v_slider, self.v_label = self._make_slider("V", 0, 255, self.hsv_values[2])
        for sl, lbl in [(self.h_slider, self.h_label), (self.s_slider, self.s_label), (self.v_slider, self.v_label)]:
            row = QHBoxLayout()
            row.addWidget(QLabel(lbl.text().split(":")[0] + ":"))
            row.addWidget(sl)
            row.addWidget(lbl)
            hsv_lay.addLayout(row)
        hsv_widget.setLayout(hsv_lay)
        tabs.addTab(hsv_widget, "HSV")

        # RGB tab
        rgb_widget = QWidget()
        rgb_lay = QVBoxLayout()
        rgb_lay.setSpacing(4)

        r, g, b = self._get_rgb()
        self.r_slider, self.r_label = self._make_slider("R", 0, 255, r)
        self.g_slider, self.g_label = self._make_slider("G", 0, 255, g)
        self.b_slider, self.b_label = self._make_slider("B", 0, 255, b)
        for sl, lbl in [(self.r_slider, self.r_label), (self.g_slider, self.g_label), (self.b_slider, self.b_label)]:
            row = QHBoxLayout()
            row.addWidget(QLabel(lbl.text().split(":")[0] + ":"))
            row.addWidget(sl)
            row.addWidget(lbl)
            rgb_lay.addLayout(row)
        rgb_widget.setLayout(rgb_lay)
        tabs.addTab(rgb_widget, "RGB")

        self.h_slider.valueChanged.connect(self._on_hsv_slider_changed)
        self.s_slider.valueChanged.connect(self._on_hsv_slider_changed)
        self.v_slider.valueChanged.connect(self._on_hsv_slider_changed)
        self.r_slider.valueChanged.connect(self._on_rgb_slider_changed)
        self.g_slider.valueChanged.connect(self._on_rgb_slider_changed)
        self.b_slider.valueChanged.connect(self._on_rgb_slider_changed)

        layout.addWidget(tabs)

        # ── Recent colors ──
        recent_group = QGroupBox("Recent Colors")
        recent_layout = QHBoxLayout()
        recent_layout.setSpacing(4)
        self.recent_buttons = []
        recent_colors = self._load_recent_colors()
        for i in range(self.MAX_RECENT):
            btn = QPushButton()
            btn.setFixedSize(28, 28)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            if i < len(recent_colors):
                c = recent_colors[i]
                btn.setStyleSheet(
                    f"background-color: rgb({c[0]},{c[1]},{c[2]}); border: 1px solid #555; border-radius: 3px;"
                )
                btn.setToolTip(f"#{c[0]:02x}{c[1]:02x}{c[2]:02x}")
                btn.clicked.connect(lambda checked, rgb=c: self._on_recent_clicked(rgb))
            else:
                btn.setStyleSheet("background-color: #2a2a2a; border: 1px solid #444; border-radius: 3px;")
                btn.setEnabled(False)
            recent_layout.addWidget(btn)
            self.recent_buttons.append(btn)
        recent_layout.addStretch()
        recent_group.setLayout(recent_layout)
        layout.addWidget(recent_group)

        # ── Palette / other configs ──
        if self.palette_colors or self.config_colors:
            palette_group = QGroupBox("Palette and Other Configs")
            palette_layout = QHBoxLayout()
            palette_layout.setSpacing(4)

            all_colors = list(self.palette_colors) + list(self.config_colors)

            seen = set()
            unique = []
            for c in all_colors:
                key = (c.get("h", 0), c.get("s", 0), c.get("v", 0))
                if key not in seen and key != (0, 0, 0):
                    seen.add(key)
                    unique.append(c)

            for c in unique[:20]:
                cr, cg, cb = self._hsv_to_rgb(c["h"], c["s"], c["v"])
                btn = QPushButton()
                btn.setFixedSize(28, 28)
                btn.setCursor(Qt.CursorShape.PointingHandCursor)
                btn.setStyleSheet(
                    f"background-color: rgb({cr},{cg},{cb}); border: 1px solid #555; border-radius: 3px;"
                )
                name = c.get("name", "")
                tip = f"{name}\n" if name else ""
                tip += f"HSV({c['h']}°, {c['s']}, {c['v']})"
                btn.setToolTip(tip)
                btn.clicked.connect(
                    lambda checked, h=c["h"], s=c["s"], v=c["v"]: self._on_palette_clicked(h, s, v)
                )
                palette_layout.addWidget(btn)

            palette_layout.addStretch()
            palette_group.setLayout(palette_layout)
            layout.addWidget(palette_group)

        # ── Buttons ──
        button_layout = QHBoxLayout()

        apply_btn = QPushButton("Apply")
        apply_btn.setFixedHeight(36)
        apply_btn.clicked.connect(self._on_apply)
        button_layout.addWidget(apply_btn)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setFixedHeight(36)
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(cancel_btn)

        layout.addLayout(button_layout)
        self.setLayout(layout)

        self._sync_from_hsv()

    def _make_slider(self, name, min_val, max_val, initial, suffix=""):
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setMinimum(min_val)
        slider.setMaximum(max_val)
        slider.setValue(int(initial))
        label = QLabel(f"{name}: {int(initial)}{suffix}")
        label.setFixedWidth(60)
        return slider, label

    # ── Sync methods ──

    def _sync_from_hsv(self):
        if self._updating:
            return
        self._updating = True

        h, s, v = self.hsv_values
        r, g, b = self._get_rgb()

        self.h_slider.setValue(int(h))
        self.s_slider.setValue(int(s))
        self.v_slider.setValue(int(v))
        self.h_label.setText(f"H: {int(h)}°")
        self.s_label.setText(f"S: {int(s)}")
        self.v_label.setText(f"V: {int(v)}")

        self.r_slider.setValue(r)
        self.g_slider.setValue(g)
        self.b_slider.setValue(b)
        self.r_label.setText(f"R: {r}")
        self.g_label.setText(f"G: {g}")
        self.b_label.setText(f"B: {b}")

        self.hex_input.setText(f"#{r:02x}{g:02x}{b:02x}")

        self.color_wheel.set_color(int(h), int(s), int(v))

        self.new_preview.setStyleSheet(
            f"background-color: rgb({r},{g},{b}); border: 1px solid #555; border-radius: 4px;"
        )

        self._updating = False

    # ── Event handlers ──

    def _on_hsv_slider_changed(self):
        if self._updating:
            return
        self.hsv_values[0] = self.h_slider.value()
        self.hsv_values[1] = self.s_slider.value()
        self.hsv_values[2] = self.v_slider.value()
        self._sync_from_hsv()

    def _on_rgb_slider_changed(self):
        if self._updating:
            return
        r = self.r_slider.value()
        g = self.g_slider.value()
        b = self.b_slider.value()
        h, s, v = self._rgb_to_hsv(r, g, b)
        self.hsv_values = [int(h), int(s), int(v)]
        self._sync_from_hsv()

    def _on_hex_changed(self):
        if self._updating:
            return
        text = self.hex_input.text().strip()
        if len(text) == 7 and text.startswith("#"):
            try:
                r = int(text[1:3], 16)
                g = int(text[3:5], 16)
                b = int(text[5:7], 16)
                h, s, v = self._rgb_to_hsv(r, g, b)
                self.hsv_values = [int(h), int(s), int(v)]
                self._sync_from_hsv()
            except ValueError:
                pass

    def _on_wheel_changed(self, h, s, v):
        if self._updating:
            return
        self.hsv_values = [h, s, v]
        self._sync_from_hsv()

    def _on_recent_clicked(self, rgb):
        r, g, b = rgb
        h, s, v = self._rgb_to_hsv(r, g, b)
        self.hsv_values = [int(h), int(s), int(v)]
        self._sync_from_hsv()

    def _on_palette_clicked(self, h, s, v):
        self.hsv_values = [h, s, v]
        self._sync_from_hsv()

    # ── Color conversion ──

    def _get_rgb(self):
        h = self.hsv_values[0] / 360.0
        s = self.hsv_values[1] / 255.0
        v = self.hsv_values[2] / 255.0
        r, g, b = colorsys.hsv_to_rgb(h, s, v)
        return (int(r * 255), int(g * 255), int(b * 255))

    def _rgb_to_hsv(self, r, g, b):
        h, s, v = colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)
        return (h * 360.0, s * 255.0, v * 255.0)

    @staticmethod
    def _hsv_to_rgb(h, s, v):
        r, g, b = colorsys.hsv_to_rgb(h / 360.0, s / 255.0, v / 255.0)
        return (int(r * 255), int(g * 255), int(b * 255))

    # ── Recent colors persistence ──

    def _load_recent_colors(self):
        settings = QSettings("TUXEDO", "KeyboardViewer")
        data = settings.value("recent_colors", [])
        if isinstance(data, list):
            return data[:self.MAX_RECENT]
        return []

    def _save_recent_color(self, r, g, b):
        recent = self._load_recent_colors()
        entry = [r, g, b]
        recent = [c for c in recent if c != entry]
        recent.insert(0, entry)
        recent = recent[:self.MAX_RECENT]
        settings = QSettings("TUXEDO", "KeyboardViewer")
        settings.setValue("recent_colors", recent)

    # ── Apply ──

    def _on_apply(self):
        h = int(self.hsv_values[0])
        s = int(self.hsv_values[1])
        v = int(self.hsv_values[2])
        r, g, b = self._get_rgb()
        self._save_recent_color(r, g, b)
        self.color_selected.emit(self.preset_index, h, s, v)
        self.accept()

    def get_color(self):
        return self._get_rgb()
