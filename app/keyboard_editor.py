#!/usr/bin/env python3
"""
TUXEDO Keyboard Colors - PyQt6 GUI Editor
Visual keyboard layout editor with per-key color control
"""

import sys
import os
import signal
import colorsys
import copy
import json
import re
from pathlib import Path
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout,
    QLabel, QMessageBox, QToolBar, QStatusBar,
    QGraphicsView, QGraphicsScene,
    QGraphicsTextItem, QSizePolicy, QMenu,
    QHBoxLayout, QPushButton, QComboBox, QGraphicsDropShadowEffect,
    QGraphicsPathItem, QSystemTrayIcon, QDialog, QInputDialog, QScrollArea
)
from PyQt6.QtCore import (
    Qt, QSettings, QTimer, QThread, pyqtSignal, QRectF
)
from PyQt6.QtGui import (
    QColor, QPen, QBrush, QFont, QIcon, QPixmap, QAction, QPalette,
    QPainter, QPainterPath, QKeySequence, QShortcut, QActionGroup
)

from keyboard_config import ColorConfigManager
from color_picker import HSVColorPicker
from __version__ import __version__


FONT_FAMILY = "Noto Sans"


class KeyboardGraphicsView(QGraphicsView):
    """QGraphicsView for keyboard with paint-drag support (left=color, right=black)."""

    def __init__(self, parent_gui):
        super().__init__()
        self._parent_gui = parent_gui
        self._left_button_down = False
        self._right_button_down = False
        self._has_reset_hover = False

    def mousePressEvent(self, event):
        # Check if we clicked on a key or on empty space
        item = self.itemAt(event.pos())
        # If we hit a text label, get the parent KeyItem
        if item and not hasattr(item, 'key_hex') and item.parentItem():
            item = item.parentItem()
        
        # If clicking on empty space (no key), deselect all
        if not item or not hasattr(item, 'key_hex'):
            if self._parent_gui.selected_keys:
                self._parent_gui._deselect_all_keys()
        
        if event.button() == Qt.MouseButton.LeftButton:
            self._left_button_down = True
            self._parent_gui.is_dragging = True
            self._has_reset_hover = False
        elif event.button() == Qt.MouseButton.RightButton:
            self._right_button_down = True
            self._parent_gui.is_dragging = True
            self._has_reset_hover = False
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if (self._left_button_down or self._right_button_down) and not self._has_reset_hover:
            self._parent_gui._reset_all_hover()
            self._has_reset_hover = True
        
        if self._left_button_down and self._parent_gui.selected_preset_idx is not None:
            item = self.itemAt(event.pos())
            # If we hit a text label, get the parent KeyItem
            if item and not hasattr(item, 'key_hex') and not hasattr(item, 'zone') and item.parentItem():
                item = item.parentItem()
            if item and hasattr(item, 'key_hex'):
                self._parent_gui._paint_key(item.key_hex)
            elif item and hasattr(item, 'side'):
                self._parent_gui._paint_lightbar(item.side, self._parent_gui.selected_preset_idx)
        elif self._right_button_down:
            item = self.itemAt(event.pos())
            # If we hit a text label, get the parent KeyItem
            if item and not hasattr(item, 'key_hex') and not hasattr(item, 'zone') and item.parentItem():
                item = item.parentItem()
            if item and hasattr(item, 'key_hex'):
                self._parent_gui._paint_key_black(item.key_hex)
            elif item and hasattr(item, 'side'):
                self._parent_gui._paint_lightbar(item.side, 0)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._left_button_down = False
        elif event.button() == Qt.MouseButton.RightButton:
            self._right_button_down = False
        self._parent_gui.is_dragging = False
        super().mouseReleaseEvent(event)


# ═══════════════════════════════════════════════════════
# Async hardware write worker
# ═══════════════════════════════════════════════════════

class HardwareWriteWorker(QThread):
    """Background thread for file save + hardware sysfs write"""
    finished = pyqtSignal(bool, str)  # (success, message)

    def __init__(self, manager, config, config_path, keys_dirty, lightbar_dirty):
        super().__init__()
        self.manager = manager
        self.config = config
        self.config_path = config_path
        self.keys_dirty = keys_dirty
        self.lightbar_dirty = lightbar_dirty

    def run(self):
        try:
            self.manager.save_config(self.config, str(self.config_path))
            # Only apply what changed
            if self.keys_dirty and self.lightbar_dirty:
                self.manager.apply_config(self.config)  # Full apply
            elif self.keys_dirty:
                self.manager.apply_config(self.config, changed_preset_idx=-1)  # Keys only
            elif self.lightbar_dirty:
                self.manager.apply_config(self.config, changed_preset_idx=-2)  # Lightbar only
            self.finished.emit(True, "Applied")
        except PermissionError:
            self.finished.emit(False, "Saved but kernel apply failed (need sudo)")
        except Exception as e:
            self.finished.emit(False, f"Apply failed: {e}")


class KeyItem(QGraphicsPathItem):
    """Custom graphics item for a keyboard key with rounded corners and selection support"""
    
    BORDER_DEFAULT = QColor('#505050')
    BORDER_HOVER = QColor("#00CDE4")
    BORDER_SELECTED = QColor("#EFB700")
    BG_DEFAULT = QColor('#2a2a2a')
    CORNER_RADIUS = 5
    
    def __init__(self, key_hex, x, y, width, height, label, key_name, parent_gui):
        # Build rounded rect path
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, width, height), self.CORNER_RADIUS, self.CORNER_RADIUS)
        super().__init__(path)
        
        self.key_hex = key_hex
        self.key_name = key_name
        self.parent_gui = parent_gui
        self._width = width
        self._height = height
        self._selected = False
        self._current_color = self.BG_DEFAULT
        
        self.setPos(x, y)
        
        # Default styling
        self.setPen(QPen(self.BORDER_DEFAULT, 2))
        self.setBrush(QBrush(self.BG_DEFAULT))
        self.setAcceptHoverEvents(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        
        # Label text (drawn in paint())
        self._label = label
        self._text_color = QColor('#cccccc')
        self._font = QFont(FONT_FAMILY, 9, QFont.Weight.Bold)
        
        # Shadow params
        self._shadow_offset = 1.5
        self._shadow_color = QColor(0, 0, 0, 80)
        
        # Set initial color
        self.update_color()
    
    def boundingRect(self):
        br = super().boundingRect()
        return br.adjusted(0, 0, self._shadow_offset + 1, self._shadow_offset + 1)
    
    def paint(self, painter, option, widget=None):
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        # Draw shadow
        shadow_path = QPainterPath()
        shadow_path.addRoundedRect(
            QRectF(self._shadow_offset, self._shadow_offset,
                   self._width, self._height),
            self.CORNER_RADIUS, self.CORNER_RADIUS)
        painter.fillPath(shadow_path, self._shadow_color)
        # Draw key background and border
        super().paint(painter, option, widget)
        # Draw label text
        painter.setFont(self._font)
        painter.setPen(QPen(self._text_color))
        painter.drawText(QRectF(0, 0, self._width, self._height),
                         Qt.AlignmentFlag.AlignCenter, self._label)
    
    def set_selected(self, selected):
        self._selected = selected
        self._apply_border()
    
    def _apply_border(self):
        if self._selected:
            self.setPen(QPen(self.BORDER_SELECTED, 3))
        else:
            self.setPen(QPen(self.BORDER_DEFAULT, 2))
    
    def update_color(self):
        """Update the key's color based on current config"""
        color = self.BG_DEFAULT
        for key in self.parent_gui.current_config['keys']:
            if key['id'] == int(self.key_hex, 16):
                preset_idx = key.get('preset', 0)
                presets = self.parent_gui.presets
                if 0 <= preset_idx < len(presets):
                    preset = presets[preset_idx]
                    h = preset.get("h", 0)
                    s = preset.get("s", 255)
                    v = preset.get("v", 255)
                    r, g, b = colorsys.hsv_to_rgb(h/360.0, s/255.0, v/255.0)
                    r, g, b = int(r * 255), int(g * 255), int(b * 255)
                    color = QColor(r, g, b)
                break
        self._current_color = color
        self.setBrush(QBrush(color))
        
        # Adjust text color based on background luminance
        luminance = (0.2126 * color.red() + 0.7152 * color.green() + 0.0722 * color.blue()) / 255.0
        self._text_color = QColor('#000000') if luminance > 0.4 else QColor('#ffffff')
        self.update()
    
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.parent_gui._on_key_click(self.key_hex, self.key_name, event)
        elif event.button() == Qt.MouseButton.RightButton:
            self.parent_gui._on_key_right_click(self.key_hex, self.key_name)
        super().mousePressEvent(event)
    
    def hoverEnterEvent(self, event):
        if self.parent_gui.is_dragging:
            return
        if not self._selected:
            self.setPen(QPen(self.BORDER_HOVER, 3))
        # Slightly lighten the color
        lighter = self._current_color.lighter(120)
        self.setBrush(QBrush(lighter))
        super().hoverEnterEvent(event)
    
    def hoverLeaveEvent(self, event):
        self._apply_border()
        self.setBrush(QBrush(self._current_color))
        super().hoverLeaveEvent(event)
    
    def reset_hover(self):
        """Reset hover state (used when drag starts)"""
        self._apply_border()
        self.setBrush(QBrush(self._current_color))
    
    def set_label(self, label):
        """Update the displayed label text"""
        self._label = label
        self.update()


class LightbarItem(QGraphicsPathItem):
    """Clickable circle representing one lightbar LED"""

    BORDER_DEFAULT = QColor('#505050')
    BORDER_HOVER = QColor('#00AAFF')
    BORDER_SELECTED = QColor('#FFD700')
    BG_DEFAULT = QColor('#2a2a2a')

    def __init__(self, side, zone, x, y, diameter, parent_gui):
        path = QPainterPath()
        path.addEllipse(QRectF(0, 0, diameter, diameter))
        super().__init__(path)

        self.side = side        # 'left' or 'right'
        self.zone = zone        # 0x10 or 0x20
        self.parent_gui = parent_gui
        self._diameter = diameter
        self._current_color = self.BG_DEFAULT

        self.setPos(x, y)
        self.setPen(QPen(self.BORDER_DEFAULT, 2))
        self.setBrush(QBrush(self.BG_DEFAULT))
        self.setAcceptHoverEvents(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(8)
        shadow.setOffset(1, 1)
        shadow.setColor(QColor(0, 0, 0, 120))
        self.setGraphicsEffect(shadow)

        self.update_color()

    def update_color(self):
        """Update color from config lightbar preset"""
        color = self.BG_DEFAULT
        lightbar = self.parent_gui.current_config.get('lightbar', {})
        preset_idx = lightbar.get(self.side, {}).get('preset', 0)
        presets = self.parent_gui.presets
        if 0 <= preset_idx < len(presets):
            preset = presets[preset_idx]
            h = preset.get('h', 0)
            s = preset.get('s', 255)
            v = preset.get('v', 255)
            r, g, b = colorsys.hsv_to_rgb(h / 360.0, s / 255.0, v / 255.0)
            color = QColor(int(r * 255), int(g * 255), int(b * 255))
        self._current_color = color
        self.setBrush(QBrush(color))

    def get_rgb(self):
        """Return current (r, g, b) tuple"""
        return (self._current_color.red(), self._current_color.green(), self._current_color.blue())

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            if self.parent_gui.selected_preset_idx is not None:
                self.parent_gui._paint_lightbar(self.side, self.parent_gui.selected_preset_idx)
        elif event.button() == Qt.MouseButton.RightButton:
            self.parent_gui._paint_lightbar(self.side, 0)
        super().mousePressEvent(event)

    def hoverEnterEvent(self, event):
        if self.parent_gui.is_dragging:
            return
        self.setPen(QPen(self.BORDER_HOVER, 3))
        self.setBrush(QBrush(self._current_color.lighter(120)))
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        self.setPen(QPen(self.BORDER_DEFAULT, 2))
        self.setBrush(QBrush(self._current_color))
        super().hoverLeaveEvent(event)

    def reset_hover(self):
        self.setPen(QPen(self.BORDER_DEFAULT, 2))
        self.setBrush(QBrush(self._current_color))


class LightbarGradientItem(QGraphicsPathItem):
    """Decorative gradient bar between the two lightbar LEDs"""

    def __init__(self, x, y, width, height):
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, width, height), height / 2, height / 2)
        super().__init__(path)

        self.setPos(x, y)
        self._width = width
        self._height = height
        self.setPen(QPen(Qt.PenStyle.NoPen))
        self.setZValue(-0.5)

    def update_gradient(self, left_rgb, right_rgb):
        """Update the gradient from left to right LED colors"""
        from PyQt6.QtGui import QLinearGradient
        grad = QLinearGradient(0, 0, self._width, 0)
        grad.setColorAt(0, QColor(*left_rgb))
        grad.setColorAt(1, QColor(*right_rgb))
        self.setBrush(QBrush(grad))


class KeyboardViewerGUI(QMainWindow):
    """Main window for the keyboard layout editor"""
    
    def __init__(self):
        super().__init__()
        
        try:
            self.manager = ColorConfigManager()
        except Exception as e:
            QMessageBox.critical(None, "Error", f"Failed to initialize:\n{e}")
            sys.exit(1)
        
        self.config_dir = Path(__file__).resolve().parent.parent / "configs"
        self.last_config_file = self.config_dir / ".last_config"
        
        # Read last used config, fallback to tuxedo.json
        last_config_name = "tuxedo.json"
        if self.last_config_file.exists():
            try:
                last_config_name = self.last_config_file.read_text().strip()
            except Exception:
                pass
        
        self.current_config_path = self.config_dir / last_config_name
        
        # Create default config if it doesn't exist
        if not self.current_config_path.exists():
            # Fallback to tuxedo.json if last config doesn't exist
            self.current_config_path = self.config_dir / "tuxedo.json"
            if not self.current_config_path.exists():
                self.current_config = self.manager.create_blank_config(name="TUXEDO", all_black=True)
                self.manager.save_config(self.current_config, str(self.current_config_path))
            else:
                self.current_config = self.manager.load_config(str(self.current_config_path))
        else:
            self.current_config = self.manager.load_config(str(self.current_config_path))
        
        self.current_config_filename = self.current_config_path.name
        self._save_last_config()
        
        self.key_items = {}
        self.lightbar_items = {}   # 'left' / 'right' -> LightbarItem
        self.lightbar_gradient = None
        
        self.selected_preset_idx = None
        self.selected_color = None
        
        self.selected_keys = set()
        self.is_dragging = False
        
        # Async hardware write infrastructure
        self._write_worker = None
        self._write_dirty_keys = False
        self._write_dirty_lightbar = False
        self._debounce_timer = QTimer()
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.setInterval(100)
        self._debounce_timer.timeout.connect(self._flush_hardware_write)
        
        self.setWindowTitle("Tuxedo NB04 RGB")
        self.resize(1400, 700)
        
        self._setup_ui()
        self._setup_shortcuts()
        self._setup_tray()
        self._draw_keyboard()
        self._schedule_hardware_write(keys=True, lightbar=True)  # Full apply on startup
        self.status_bar.showMessage(f"Loaded config: {self.current_config_filename}")
    
    def _setup_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout()
        central_widget.setLayout(main_layout)
        
        # Menu bar
        menubar = self.menuBar()
        
        # File menu
        file_menu = menubar.addMenu("&File")
        new_action = QAction("&New Config...", self)
        new_action.setShortcut("Ctrl+N")
        new_action.triggered.connect(self._new_config)
        file_menu.addAction(new_action)
        
        duplicate_action = QAction("&Duplicate Current Config...", self)
        duplicate_action.setShortcut("Ctrl+D")
        duplicate_action.triggered.connect(self._duplicate_config)
        file_menu.addAction(duplicate_action)
        
        delete_action = QAction("D&elete Current Config...", self)
        delete_action.triggered.connect(self._delete_config)
        file_menu.addAction(delete_action)
        
        rename_action = QAction("&Rename Current Config...", self)
        rename_action.triggered.connect(self._rename_config)
        file_menu.addAction(rename_action)
        
        file_menu.addSeparator()
        quit_action = QAction("&Quit", self)
        quit_action.setShortcut("Ctrl+Q")
        quit_action.triggered.connect(self._quit_app)
        file_menu.addAction(quit_action)
        
        # View menu
        view_menu = menubar.addMenu("&View")

        theme_menu = view_menu.addMenu("Theme")
        for name in ("Light", "Dark", "System"):
            action = QAction(name, self)
            action.triggered.connect(lambda checked, n=name.lower(): self._set_theme(n))
            theme_menu.addAction(action)

        view_menu.addSeparator()
        
        # Help menu
        help_menu = menubar.addMenu("&Help")
        how_to_action = QAction("&How to Use", self)
        how_to_action.setShortcut("F1")
        how_to_action.triggered.connect(self._show_how_to_use)
        help_menu.addAction(how_to_action)
        
        help_menu.addSeparator()
        
        about_action = QAction("&About", self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)
        
        # Toolbar
        toolbar = QToolBar()
        toolbar.setMovable(False)
        self.addToolBar(toolbar)
        
        self.config_combo = QComboBox()
        self.config_combo.setMinimumWidth(200)
        self.config_combo.currentTextChanged.connect(self._on_config_changed)
        toolbar.addWidget(QLabel("Config:"))
        toolbar.addWidget(self.config_combo)
        self._load_config_list()
        
        toolbar.addSeparator()
        
        toolbar.addWidget(QLabel("Layout:"))
        self.keymap_combo = QComboBox()
        self.keymap_combo.setMinimumWidth(150)
        for name, km in self.manager.keymaps.items():
            self.keymap_combo.addItem(km.get("name", name), name)
        settings = QSettings("TUXEDO", "KeyboardViewer")
        saved_keymap = settings.value("keymap", "qwerty-us")
        for i in range(self.keymap_combo.count()):
            if self.keymap_combo.itemData(i) == saved_keymap:
                self.keymap_combo.setCurrentIndex(i)
                break
        self.current_keymap = saved_keymap
        self.keymap_combo.currentIndexChanged.connect(self._on_keymap_changed)
        toolbar.addWidget(self.keymap_combo)
        
        toolbar.addSeparator()
        
        reload_btn = QPushButton("Reload")
        reload_btn.setMaximumWidth(80)
        reload_btn.setToolTip("Reload config from disk (Ctrl+R)")
        reload_btn.clicked.connect(self._reload_current_config)
        toolbar.addWidget(reload_btn)
        
        reload_shortcut = QShortcut(QKeySequence("Ctrl+R"), self)
        reload_shortcut.activated.connect(self._reload_current_config)
        
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        toolbar.addWidget(spacer)
        
        self.info_label = QLabel()
        self.info_label.setStyleSheet(f"font-family: '{FONT_FAMILY}'; color: #cccccc; font-weight: bold; font-size: 14px;")
        toolbar.addWidget(self.info_label)
        
        # Keyboard view
        self.view = KeyboardGraphicsView(self)
        self.scene = QGraphicsScene()
        self.view.setScene(self.scene)
        self.view.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.view.setBackgroundBrush(QBrush(QColor('#1e1e1e')))
        self.view.setDragMode(QGraphicsView.DragMode.NoDrag)
        main_layout.addWidget(self.view)

        # Color bar container
        self.color_bar_widget = QWidget()
        self.color_bar_layout = QHBoxLayout()
        self.color_bar_layout.setSpacing(6)
        self.color_bar_layout.setContentsMargins(4, 4, 4, 4)
        self.color_bar_widget.setLayout(self.color_bar_layout)
        main_layout.addWidget(self.color_bar_widget)
        self._setup_color_bar()

        # Status bar
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Click a palette colour to select  |  Left-drag to paint keys  |  Right-drag to reset keys")
    
    def _setup_shortcuts(self):
        select_all = QShortcut(QKeySequence("Ctrl+A"), self)
        select_all.activated.connect(self._select_all_keys)
        deselect = QShortcut(QKeySequence("Escape"), self)
        deselect.activated.connect(self._deselect_all_keys)
    
    def _select_all_keys(self):
        self.selected_keys = set(self.key_items.keys())
        for key_item in self.key_items.values():
            key_item.set_selected(True)
        self.status_bar.showMessage(f"Selected all {len(self.selected_keys)} keys")
    
    def _deselect_all_keys(self):
        for hex_code in self.selected_keys:
            if hex_code in self.key_items:
                self.key_items[hex_code].set_selected(False)
        self.selected_keys.clear()
    
    def _toggle_key_selection(self, key_hex):
        if key_hex in self.selected_keys:
            self.selected_keys.discard(key_hex)
            self.key_items[key_hex].set_selected(False)
        else:
            self.selected_keys.add(key_hex)
            self.key_items[key_hex].set_selected(True)

    def _paint_key(self, key_hex):
        """Paint a single key with the currently selected color."""
        if self.selected_preset_idx is None or key_hex not in self.key_items:
            return
        key_id = int(key_hex, 16)
        self.manager.add_key_to_config(self.current_config, key_id, self.selected_preset_idx)
        self.key_items[key_hex].update_color()
        self._schedule_hardware_write(keys=True, lightbar=False)

    def _paint_key_black(self, key_hex):
        """Paint a single key black (preset 0)."""
        if key_hex not in self.key_items:
            return
        key_id = int(key_hex, 16)
        self.manager.add_key_to_config(self.current_config, key_id, 0)
        self.key_items[key_hex].update_color()
        self._schedule_hardware_write(keys=True, lightbar=False)

    def _paint_lightbar(self, side, preset_idx):
        """Paint a lightbar LED with a preset."""
        lightbar = self.current_config.setdefault('lightbar', {})
        lightbar.setdefault(side, {})['preset'] = preset_idx
        if side in self.lightbar_items:
            self.lightbar_items[side].update_color()
        self._update_lightbar_gradient()
        self._schedule_hardware_write(keys=False, lightbar=True)

    def _update_lightbar_gradient(self):
        """Refresh the gradient bar between lightbar LEDs."""
        if self.lightbar_gradient and 'left' in self.lightbar_items and 'right' in self.lightbar_items:
            self.lightbar_gradient.update_gradient(
                self.lightbar_items['left'].get_rgb(),
                self.lightbar_items['right'].get_rgb(),
            )

    def _reset_all_hover(self):
        """Reset hover state on all keys and lightbar items (called when drag starts)"""
        for key_item in self.key_items.values():
            key_item.reset_hover()
        for lb_item in self.lightbar_items.values():
            lb_item.reset_hover()

    def _schedule_hardware_write(self, keys=True, lightbar=True):
        if keys:
            self._write_dirty_keys = True
        if lightbar:
            self._write_dirty_lightbar = True
        self._debounce_timer.start()

    def _flush_hardware_write(self):
        if not self._write_dirty_keys and not self._write_dirty_lightbar:
            return

        if self._write_worker is not None and self._write_worker.isRunning():
            self._debounce_timer.start()
            return

        import copy
        config_snapshot = copy.deepcopy(self.current_config)
        keys_dirty = self._write_dirty_keys
        lightbar_dirty = self._write_dirty_lightbar
        self._write_dirty_keys = False
        self._write_dirty_lightbar = False

        self._write_worker = HardwareWriteWorker(
            self.manager, config_snapshot, self.current_config_path, keys_dirty, lightbar_dirty
        )
        self._write_worker.finished.connect(self._on_hardware_write_done)
        self.status_bar.showMessage("Applying...")
        self._write_worker.start()

    def _on_hardware_write_done(self, success, message):
        self.status_bar.showMessage(message)
        if self._write_dirty_keys or self._write_dirty_lightbar:
            self._debounce_timer.start()

    # ── Color Bar (bottom) ──

    def _swatch_style(self, r, g, b, selected=False):
        base = f"background-color: rgb({r},{g},{b}); border-radius: 6px;"
        if selected:
            return (
                f"QPushButton {{ {base} border: 3px solid #FFD700; }} "
                f"QPushButton:hover {{ {base} border: 3px solid #FFD700; }}"
            )
        return (
            f"QPushButton {{ {base} border: 2px solid #555; }} "
            f"QPushButton:hover {{ {base} border: 3px solid #00AAFF; }}"
        )

    def _setup_color_bar(self):
        """(Re)build the color swatch bar. Uses self.color_bar_layout directly — no nesting."""
        while self.color_bar_layout.count():
            item = self.color_bar_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        self.presets = self.manager.get_or_create_presets(self.current_config)
        self.color_buttons = []

        for idx, preset in enumerate(self.presets):
            h = preset.get("h", 0)
            s = preset.get("s", 255)
            v = preset.get("v", 255)
            r, g, b = colorsys.hsv_to_rgb(h / 360.0, s / 255.0, v / 255.0)
            r, g, b = int(r * 255), int(g * 255), int(b * 255)

            btn = QPushButton()
            btn.setFixedSize(40, 40)
            btn.setStyleSheet(self._swatch_style(r, g, b, selected=False))
            btn.clicked.connect(lambda checked, i=idx: self._on_color_swatch_click(i))
            btn.mouseDoubleClickEvent = lambda event, i=idx: self._on_color_double_click(i)
            btn.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            btn.customContextMenuRequested.connect(
                lambda pos, i=idx, b=btn: self._on_swatch_context_menu(i, b)
            )
            btn.setToolTip(f"#{r:02x}{g:02x}{b:02x}")
            self.color_bar_layout.addWidget(btn)
            self.color_buttons.append((btn, preset, idx))

        # Add color button
        add_btn = QPushButton("+")
        add_btn.setFixedSize(40, 40)
        add_btn.setToolTip("Add new colour")
        add_btn.setStyleSheet(
            f"QPushButton {{ font-family: '{FONT_FAMILY}'; font-size: 18px; font-weight: bold; "
            f"border: 2px dashed #666; border-radius: 6px; color: #aaa; background: #2a2a2a; }} "
            f"QPushButton:hover {{ font-family: '{FONT_FAMILY}'; font-size: 18px; font-weight: bold; "
            f"border: 2px dashed #00AAFF; border-radius: 6px; color: #ddd; background: #2a2a2a; }}"
        )
        add_btn.clicked.connect(self._on_add_color)
        self.color_bar_layout.addWidget(add_btn)
        self.color_bar_layout.addStretch()

    def _on_color_swatch_click(self, preset_idx):
        """Left-click: select this color for painting, apply to selected keys if any"""
        if preset_idx >= len(self.presets):
            return

        preset = self.presets[preset_idx]
        h, s, v = preset.get("h", 0), preset.get("s", 255), preset.get("v", 255)
        self.selected_color = (h, s, v)
        self.selected_preset_idx = preset_idx

        r, g, b = colorsys.hsv_to_rgb(h / 360.0, s / 255.0, v / 255.0)
        r, g, b = int(r * 255), int(g * 255), int(b * 255)

        # Update swatch borders
        for btn, p, idx in self.color_buttons:
            ph, ps, pv = p.get("h", 0), p.get("s", 255), p.get("v", 255)
            pr, pg, pb = colorsys.hsv_to_rgb(ph / 360.0, ps / 255.0, pv / 255.0)
            pr, pg, pb = int(pr * 255), int(pg * 255), int(pb * 255)
            btn.setStyleSheet(self._swatch_style(pr, pg, pb, selected=(idx == preset_idx)))

        # Apply to selected keys
        if self.selected_keys:
            for key_hex in self.selected_keys:
                key_id = int(key_hex, 16)
                self.manager.add_key_to_config(self.current_config, key_id, preset_idx)
                self.key_items[key_hex].update_color()
            self._schedule_hardware_write(keys=True, lightbar=False)  # Only keys changed
            self.status_bar.showMessage(
                f"Applied colour to {len(self.selected_keys)} keys"
            )
        else:
            self.status_bar.showMessage(
                f"Selected colour {preset_idx}: #{r:02x}{g:02x}{b:02x}"
            )

    def _on_swatch_context_menu(self, preset_idx, button):
        """Right-click context menu on color swatch"""
        menu = QMenu(self)

        if preset_idx != 0:
            edit_action = QAction("Edit Colour...", self)
            edit_action.triggered.connect(lambda: self._edit_color(preset_idx))
            menu.addAction(edit_action)

        save_action = QAction("Save to Palette", self)
        save_action.triggered.connect(lambda: self._save_color_to_palette(preset_idx))
        menu.addAction(save_action)

        if preset_idx != 0:
            menu.addSeparator()
            remove_action = QAction("Remove Colour", self)
            remove_action.triggered.connect(lambda: self._remove_color(preset_idx))
            menu.addAction(remove_action)

        menu.exec(button.mapToGlobal(button.rect().bottomLeft()))

    def _edit_color(self, preset_idx):
        """Open color picker to edit a color"""
        if preset_idx >= len(self.presets):
            return
        preset = self.presets[preset_idx]
        h, s, v = preset.get("h", 0), preset.get("s", 255), preset.get("v", 255)

        picker = HSVColorPicker(
            self,
            preset_index=preset_idx,
            initial_h=h,
            initial_s=s,
            initial_v=v,
            palette_colors=self.manager.load_palette(),
            config_colors=self.manager.get_colors_from_all_configs(
                exclude_path=str(self.current_config_path)
            ),
        )
        picker.color_selected.connect(self._on_preset_color_updated)
        picker.exec()
    
    def _on_color_double_click(self, preset_idx):
        """Handle double-click on color button - open color picker"""
        self._edit_color(preset_idx)

    def _on_add_color(self):
        """Add new color - opens picker, appends at end on Apply"""
        picker = HSVColorPicker(
            self,
            preset_index=-1,
            initial_h=0,
            initial_s=255,
            initial_v=255,
            palette_colors=self.manager.load_palette(),
            config_colors=self.manager.get_colors_from_all_configs(
                exclude_path=str(self.current_config_path)
            ),
        )
        picker.color_selected.connect(self._on_new_color_picked)
        picker.exec()

    def _on_new_color_picked(self, _preset_idx, h, s, v):
        """Handle new color from picker"""
        new_idx = self.manager.add_preset(self.current_config, h=h, s=s, v=v)
        if new_idx >= 0:
            self.presets = self.manager.get_or_create_presets(self.current_config)
            # No schedule needed - new preset not used yet
            self._setup_color_bar()
            self._on_color_swatch_click(new_idx)
            self.status_bar.showMessage(f"Added colour {new_idx}")

    def _remove_color(self, preset_idx):
        """Remove a color swatch"""
        if preset_idx == 0:
            return

        reply = QMessageBox.question(
            self,
            "Remove Colour?",
            "Remove this colour?\nKeys using it will switch to black.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        success = self.manager.remove_preset(self.current_config, preset_idx)
        if success:
            self.selected_preset_idx = None
            self.presets = self.manager.get_or_create_presets(self.current_config)
            self._schedule_hardware_write(keys=True, lightbar=True)  # Both may have used this preset
            self._setup_color_bar()
            for key_item in self.key_items.values():
                key_item.update_color()
            for lb_item in self.lightbar_items.values():
                lb_item.update_color()
            self._update_lightbar_gradient()
            self.status_bar.showMessage("Removed colour")

    def _save_color_to_palette(self, preset_idx):
        """Save a color swatch to global palette"""
        if preset_idx < 0 or preset_idx >= len(self.presets):
            return
        preset = self.presets[preset_idx]
        h, s, v = preset.get("h", 0), preset.get("s", 0), preset.get("v", 0)
        self.manager.save_to_palette(h, s, v)
        self.status_bar.showMessage("Saved colour to palette")

    def _on_preset_color_updated(self, preset_idx, h, s, v):
        """Handle color update from color picker"""
        if preset_idx >= len(self.presets):
            return

        success = self.manager.update_preset(self.current_config, preset_idx, h, s, v)
        if not success:
            self.status_bar.showMessage(f"Could not update colour {preset_idx}")
            return

        self.presets[preset_idx]["h"] = h
        self.presets[preset_idx]["s"] = s
        self.presets[preset_idx]["v"] = v

        r, g, b = colorsys.hsv_to_rgb(h / 360.0, s / 255.0, v / 255.0)
        r, g, b = int(r * 255), int(g * 255), int(b * 255)

        # Update the swatch button
        if preset_idx < len(self.color_buttons):
            btn, _preset, _idx = self.color_buttons[preset_idx]
            is_selected = (preset_idx == self.selected_preset_idx)
            btn.setStyleSheet(self._swatch_style(r, g, b, selected=is_selected))
            btn.setToolTip(f"#{r:02x}{g:02x}{b:02x}")

        # Update all keys using this color
        for key in self.current_config['keys']:
            if key.get('preset') == preset_idx:
                key_hex = f"0x{key['id']:02x}"
                if key_hex in self.key_items:
                    self.key_items[key_hex].update_color()

        # Update lightbar items if they use this preset
        lightbar = self.current_config.get('lightbar', {})
        lightbar_uses_preset = any(
            lightbar.get(side, {}).get('preset') == preset_idx for side in ('left', 'right')
        )
        if lightbar_uses_preset:
            for side in ('left', 'right'):
                if lightbar.get(side, {}).get('preset') == preset_idx and side in self.lightbar_items:
                    self.lightbar_items[side].update_color()
            self._update_lightbar_gradient()

        # Determine what changed: check if any keys or lightbar use this preset
        keys_use_preset = any(key.get('preset') == preset_idx for key in self.current_config['keys'])
        self._schedule_hardware_write(keys=keys_use_preset, lightbar=lightbar_uses_preset)
        self.status_bar.showMessage(f"Updated colour {preset_idx} to #{r:02x}{g:02x}{b:02x}")
    
    def _set_theme(self, theme_name):
        app = QApplication.instance()
        settings = QSettings("TUXEDO", "KeyboardViewer")
        settings.setValue("theme", theme_name)

        if theme_name == "light":
            app.setStyle("Fusion")
            palette = QPalette()
            palette.setColor(QPalette.ColorRole.Window, Qt.GlobalColor.white)
            palette.setColor(QPalette.ColorRole.WindowText, Qt.GlobalColor.black)
            palette.setColor(QPalette.ColorRole.Base, Qt.GlobalColor.white)
            palette.setColor(QPalette.ColorRole.AlternateBase, Qt.GlobalColor.lightGray)
            palette.setColor(QPalette.ColorRole.Text, Qt.GlobalColor.black)
            palette.setColor(QPalette.ColorRole.Button, Qt.GlobalColor.lightGray)
            palette.setColor(QPalette.ColorRole.ButtonText, Qt.GlobalColor.black)
            app.setPalette(palette)
            self.info_label.setStyleSheet(f"font-family: '{FONT_FAMILY}'; color: #666666; font-weight: bold; font-size: 14px;")
            self.view.setBackgroundBrush(QBrush(QColor('#f0f0f0')))
        elif theme_name == "dark":
            app.setStyle("Fusion")
            palette = QPalette()
            palette.setColor(QPalette.ColorRole.Window, QColor(53, 53, 53))
            palette.setColor(QPalette.ColorRole.WindowText, Qt.GlobalColor.white)
            palette.setColor(QPalette.ColorRole.Base, QColor(25, 25, 25))
            palette.setColor(QPalette.ColorRole.AlternateBase, QColor(53, 53, 53))
            palette.setColor(QPalette.ColorRole.Text, Qt.GlobalColor.white)
            palette.setColor(QPalette.ColorRole.Button, QColor(53, 53, 53))
            palette.setColor(QPalette.ColorRole.ButtonText, Qt.GlobalColor.white)
            palette.setColor(QPalette.ColorRole.BrightText, Qt.GlobalColor.red)
            palette.setColor(QPalette.ColorRole.Link, QColor(42, 130, 218))
            palette.setColor(QPalette.ColorRole.Highlight, QColor(42, 130, 218))
            palette.setColor(QPalette.ColorRole.HighlightedText, Qt.GlobalColor.black)
            app.setPalette(palette)
            self.info_label.setStyleSheet(f"font-family: '{FONT_FAMILY}'; color: #cccccc; font-weight: bold; font-size: 14px;")
            self.view.setBackgroundBrush(QBrush(QColor('#0a0a0a')))
        else:
            app.setStyle("")
            app.setPalette(app.style().standardPalette())
            self.info_label.setStyleSheet(f"font-family: '{FONT_FAMILY}'; color: #cccccc; font-weight: bold; font-size: 14px;")
            self.view.setBackgroundBrush(QBrush(QColor('#1e1e1e')))

        self.status_bar.showMessage(f"Theme changed to: {theme_name}")

    def _reload_current_config(self):
        """Reload the current config from disk"""
        try:
            self.current_config = self.manager.load_config(str(self.current_config_path))
            self.presets = self.manager.get_or_create_presets(self.current_config)
            self._setup_color_bar()
            
            self._deselect_all_keys()
            for key_item in self.key_items.values():
                key_item.update_color()
            for lb_item in self.lightbar_items.values():
                lb_item.update_color()
            self._update_lightbar_gradient()
            
            self._schedule_hardware_write(keys=True, lightbar=True)  # Full reload
            self.status_bar.showMessage(f"Reloaded config from disk")
        except Exception as e:
            self.status_bar.showMessage(f"Failed to reload config: {e}")
    
    def _show_how_to_use(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("How to Use — Tuxedo NB04 RGB")
        dialog.setMinimumWidth(560)

        html = f"""
<style>
  body  {{ font-family: '{FONT_FAMILY}'; font-size: 13px; margin: 0; padding: 0; }}
  h3    {{ font-size: 13px; margin: 12px 0 2px 0; }}
  p     {{ margin: 1px 0; }}
</style>
<body>
<h3>Painting the Keyboard</h3>
<p>• Click a colour in the palette to select it</p>
<p>• Left-click a key to paint it with the selected colour</p>
<p>• Left-drag across keys to paint multiple keys at once</p>
<p>• Right-click or right-drag to reset keys to black</p>

<h3>Selecting Multiple Keys</h3>
<p>• Ctrl+A to select all keys</p>
<p>• Esc to deselect all keys</p>
<p>• Click a palette colour to apply it to all selected keys</p>

<h3>Colour Palette</h3>
<p>• Right-click a palette colour to edit or remove it</p>
<p>• Click the '+' button to add a new colour</p>
<p>• Double-click a colour to open the colour picker</p>

<h3>Configurations</h3>
<p>• Use the dropdown menu to switch between saved configs</p>
<p>• Changes are automatically saved to the current config</p>
<p>• Create, rename, or delete configs using the File menu</p>

<h3>Troubleshooting</h3>
<p>If colours aren't working after a reboot (no colours, all keys one colour, or no response):</p>
<p>1.&nbsp; Hold down the <b>Fn</b> key</p>
<p>2.&nbsp; Repeatedly press <b>Numpad *</b> (RGB+), <b>Space</b> (enable/disable keyboard lighting) and <b>Numpad +</b> (keyboard brightness+) alternately</p>
<p>3.&nbsp; When you see any colour on your keyboard, release the <b>Fn</b> key</p>
<p>Now you can press the <b>Reload</b> button or select a profile and it should work again.</p>
</body>
"""

        content = QLabel()
        content.setText(html)
        content.setTextFormat(Qt.TextFormat.RichText)
        content.setWordWrap(True)
        content.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        content.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        content.setContentsMargins(4, 4, 4, 4)

        scroll = QScrollArea()
        scroll.setWidget(content)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        close_btn = QPushButton("Close")
        close_btn.setFixedWidth(100)
        close_btn.clicked.connect(dialog.accept)
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_row.addWidget(close_btn)
        btn_row.addStretch()

        layout = QVBoxLayout()
        layout.setContentsMargins(12, 12, 12, 12)
        layout.addWidget(scroll)
        layout.addSpacing(6)
        layout.addLayout(btn_row)

        dialog.setLayout(layout)

        # Size the dialog to fit the content without scrolling, up to screen limit
        content.adjustSize()
        screen = dialog.screen().availableGeometry()
        desired_h = content.sizeHint().height() + 90  # margins + button row
        dialog.resize(dialog.minimumWidth(), min(desired_h, screen.height() - 100))
        dialog.exec()

    def _show_about(self):
        dialog = QDialog(self)
        dialog.setWindowTitle(f"About Tuxedo NB04 RGB v{__version__}")
        dialog.setMinimumWidth(400)
        layout = QVBoxLayout()
        layout.setSpacing(15)

        icon_label = QLabel()
        icon_svg = os.path.join(os.path.dirname(__file__), "..", "assets", "icon.svg")
        if os.path.exists(icon_svg):
            pixmap = QPixmap(icon_svg).scaled(80, 80, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            icon_label.setPixmap(pixmap)
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(icon_label)

        title = QLabel(f"Tuxedo NB04 RGB v{__version__}")
        title.setStyleSheet(
            f"font-family: '{FONT_FAMILY}'; font-size: 20px; font-weight: bold;"
        )
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        subtitle = QLabel("Per-key RGB configurator for TUXEDO NB04 keyboards")
        subtitle.setStyleSheet(f"font-family: '{FONT_FAMILY}'; font-size: 13px;")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(subtitle)
        
        layout.addSpacing(10)

        credits = QLabel(
            "<b>Created by</b><br>"
            "Ruben<br>"
            "<a href='mailto:ruben@rbsworks.nl'>ruben@rbsworks.nl</a>"
        )
        credits.setTextFormat(Qt.TextFormat.RichText)
        credits.setOpenExternalLinks(True)
        credits.setAlignment(Qt.AlignmentFlag.AlignCenter)
        credits.setStyleSheet(f"font-family: '{FONT_FAMILY}'; font-size: 13px;")
        layout.addWidget(credits)

        layout.addSpacing(10)
        
        help_hint = QLabel("Press   <b>F1</b>   for usage instructions")
        help_hint.setTextFormat(Qt.TextFormat.RichText)
        help_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        help_hint.setStyleSheet(f"font-family: '{FONT_FAMILY}'; font-size: 12px; color: #888;")
        layout.addWidget(help_hint)

        layout.addSpacing(6)
        close_btn = QPushButton("Close")
        close_btn.setFixedWidth(100)
        close_btn.clicked.connect(dialog.accept)
        h = QHBoxLayout()
        h.addStretch()
        h.addWidget(close_btn)
        h.addStretch()
        layout.addLayout(h)

        dialog.setLayout(layout)
        
        # Calculate and set fixed size
        dialog.adjustSize()
        dialog.setFixedSize(dialog.size())
        
        dialog.exec()

    # ── System tray ──────────────────────────────────────────────

    def _setup_tray(self):
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        self.tray_icon = QSystemTrayIcon(_app_icon(), self)
        self.tray_icon.setToolTip("Tuxedo NB04 RGB")
        self.tray_icon.activated.connect(self._on_tray_activated)
        self._rebuild_tray_menu()
        self.tray_icon.show()

    def _rebuild_tray_menu(self):
        if not hasattr(self, 'tray_icon') or self.tray_icon is None:
            return
        menu = QMenu()
        menu.addAction("Show / Hide", self._toggle_window)
        menu.addSeparator()
        
        # Use QActionGroup for radio button behavior
        action_group = QActionGroup(menu)
        action_group.setExclusive(True)
        
        for display_name, cfg_path in sorted(self.config_files.items()):
            action = menu.addAction(display_name)
            action.setCheckable(True)
            action.setChecked(Path(str(cfg_path)) == self.current_config_path)
            action.setActionGroup(action_group)
            action.triggered.connect(lambda checked, n=display_name: self._switch_config_from_tray(n))
        
        menu.addSeparator()
        menu.addAction("Quit", self._quit_app)
        self.tray_icon.setContextMenu(menu)

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self._toggle_window()

    def _toggle_window(self):
        if self.isVisible():
            self.hide()
        else:
            self.show()
            self.raise_()
            self.activateWindow()

    def _switch_config_from_tray(self, config_name):
        idx = self.config_combo.findText(config_name)
        if idx >= 0:
            self.config_combo.setCurrentIndex(idx)

    def closeEvent(self, event):
        if hasattr(self, 'tray_icon') and self.tray_icon is not None and self.tray_icon.isVisible():
            self.hide()
            event.ignore()
        else:
            event.accept()

    def _quit_app(self):
        if hasattr(self, 'tray_icon') and self.tray_icon is not None:
            self.tray_icon.hide()
        QApplication.instance().quit()

    # ── Keyboard drawing ─────────────────────────────────────────

    def _draw_keyboard(self):
        """Draw the keyboard layout with background body and lightbar"""
        
        keys = self.manager.layout['keys']
        lightbar_entries = self.manager.layout.get('lightbar', [])
        
        # Find canvas dimensions from keys
        max_x = max(key['x'] + key['width']/2 for key in keys)
        max_y = max(key['y'] + key['height']/2 for key in keys)
        min_x = min(key['x'] - key['width']/2 for key in keys)
        min_y = min(key['y'] - key['height']/2 for key in keys)
        
        # Expand bounds to include lightbar entries
        for lb in lightbar_entries:
            lb_left = lb['x'] - lb['width'] / 2
            lb_right = lb['x'] + lb['width'] / 2
            lb_top = lb['y'] - lb['height'] / 2
            lb_bottom = lb['y'] + lb['height'] / 2
            min_x = min(min_x, lb_left)
            max_x = max(max_x, lb_right)
            min_y = min(min_y, lb_top)
            max_y = max(max_y, lb_bottom)
        
        scale = 0.003
        padding = 20
        
        # Draw keyboard body background (rounded rect behind all keys)
        body_width = (max_x - min_x) * scale + padding
        body_height = (max_y - min_y) * scale + padding
        body_path = QPainterPath()
        body_path.addRoundedRect(
            QRectF(-padding/2, -padding/2, body_width, body_height), 12, 12
        )
        body_item = QGraphicsPathItem(body_path)
        body_item.setPen(QPen(QColor('#333333'), 1))
        body_item.setBrush(QBrush(QColor('#252525')))
        body_item.setZValue(-1)
        self.scene.addItem(body_item)
        
        # Draw each key
        for key in keys:
            key_hex = key['hex']
            label = self.manager.get_key_label(key_hex, self.current_keymap)
            
            # Calculate pixel positions (x,y are centers, convert to top-left)
            x = (key['x'] - min_x - key['width']/2) * scale
            y = (key['y'] - min_y - key['height']/2) * scale
            width = key['width'] * scale
            height = key['height'] * scale
            
            # Create key item
            key_item = KeyItem(key_hex, x, y, width, height, label, key['name'], self)
            self.scene.addItem(key_item)
            self.key_items[key_hex] = key_item
        
        # Draw lightbar LEDs
        for lb in lightbar_entries:
            side = 'left' if lb['zone'] == 16 else 'right'
            diameter = lb['width'] * scale
            cx = (lb['x'] - min_x) * scale - diameter / 2
            cy = (lb['y'] - min_y) * scale - diameter / 2
            
            lb_item = LightbarItem(side, lb['zone'], cx, cy, diameter, self)
            self.scene.addItem(lb_item)
            self.lightbar_items[side] = lb_item
        
        # Draw gradient bar between the two lightbar LEDs
        if 'left' in self.lightbar_items and 'right' in self.lightbar_items:
            li = self.lightbar_items['left']
            ri = self.lightbar_items['right']
            grad_x = li.pos().x()
            grad_y = li.pos().y()
            grad_w = ri.pos().x() + ri._diameter - grad_x
            grad_h = li._diameter
            if grad_w > 0:
                self.lightbar_gradient = LightbarGradientItem(grad_x, grad_y, grad_w, grad_h)
                self.scene.addItem(self.lightbar_gradient)
                self._update_lightbar_gradient()
        
        # Set scene rect
        scene_width = (max_x - min_x) * scale + padding * 2
        scene_height = (max_y - min_y) * scale + padding * 2
        self.scene.setSceneRect(-padding, -padding, scene_width, scene_height)
        
        self._update_info_label()
    
    def _update_info_label(self):
        """Update the info label"""
        total_keys = len(self.manager.layout['keys'])
        
        self.info_label.setText(
            f"Keyboard: {self.manager.layout['keyboard']} | "
            f"Total Keys: {total_keys}"
        )
    
    def _on_keymap_changed(self, index):
        """Handle keymap selection change"""
        keymap_name = self.keymap_combo.itemData(index)
        if not keymap_name:
            return
        self.current_keymap = keymap_name
        # Save preference
        settings = QSettings("TUXEDO", "KeyboardViewer")
        settings.setValue("keymap", keymap_name)
        # Update all key labels
        for key_hex, key_item in self.key_items.items():
            label = self.manager.get_key_label(key_hex, keymap_name)
            key_item.set_label(label)
        display_name = self.keymap_combo.currentText()
        self.status_bar.showMessage(f"Layout changed to: {display_name}")
    
    def _on_key_click(self, key_hex, key_name, event=None):
        # Plain click: paint with selected preset
        if self.selected_preset_idx is None:
            self.status_bar.showMessage(f"Clicked: {key_name} ({key_hex}) - No colour selected")
            return

        # If keys are selected, paint all of them
        targets = list(self.selected_keys) if self.selected_keys else [key_hex]

        for kh in targets:
            kid = int(kh, 16)
            self.manager.add_key_to_config(self.current_config, kid, self.selected_preset_idx)
            self.key_items[kh].update_color()

        self._schedule_hardware_write(keys=True, lightbar=False)  # Only keys changed

        preset = self.presets[self.selected_preset_idx]
        h, s, v = preset.get("h", 0), preset.get("s", 255), preset.get("v", 255)
        count = len(targets)
        self.status_bar.showMessage(
            f"Applied HSV({h}, {s}, {v}) to {count} key{'s' if count != 1 else ''}"
        )
    
    def _on_key_right_click(self, key_hex, key_name):
        """Handle key right-click - set to black"""
        key_id = int(key_hex, 16)
        
        self.manager.add_key_to_config(self.current_config, key_id, 0)
        self.key_items[key_hex].update_color()
        self._schedule_hardware_write(keys=True, lightbar=False)  # Only keys changed
        self.status_bar.showMessage(f"Set {key_name} ({key_hex}) to black")
    
    def _load_config_list(self):
        """Load available config files into the combo box"""
        try:
            self.config_combo.currentTextChanged.disconnect(self._on_config_changed)
        except TypeError:
            pass

        self.config_combo.clear()
        self.config_files = {}

        config_files = sorted(
            f for f in self.config_dir.glob("*.json") if f.name != "palette.json"
        )
        
        # If no configs exist, create a default one
        if not config_files:
            default_path = self.config_dir / "default.json"
            default_config = self.manager.create_blank_config(name="Default", all_black=True)
            self.manager.save_config(default_config, str(default_path))
            config_files = [default_path]

        for config_path in config_files:
            try:
                with open(config_path) as fh:
                    data = json.load(fh)
                display_name = data.get("name") or config_path.stem
            except Exception:
                display_name = config_path.stem

            # Disambiguate duplicate display names
            base = display_name
            suffix = 2
            while display_name in self.config_files:
                display_name = f"{base} ({suffix})"
                suffix += 1

            self.config_combo.addItem(display_name, str(config_path))
            self.config_files[display_name] = config_path

        # Set current config if it exists
        for i in range(self.config_combo.count()):
            if self.config_combo.itemData(i) == str(self.current_config_path):
                self.config_combo.setCurrentIndex(i)
                break

        self.config_combo.currentTextChanged.connect(self._on_config_changed)
    
    def _on_config_changed(self, config_name):
        """Handle config selection change"""
        if config_name and config_name in self.config_files:
            config_file_path = Path(str(self.config_files[config_name]))
            try:
                self.current_config = self.manager.load_config(str(config_file_path))
                self.current_config_path = config_file_path
                self.current_config_filename = config_file_path.name
                self.config_files[config_name] = config_file_path
                
                self.presets = self.manager.get_or_create_presets(self.current_config)
                self._setup_color_bar()

                self._deselect_all_keys()
                for key_item in self.key_items.values():
                    key_item.update_color()
                for lb_item in self.lightbar_items.values():
                    lb_item.update_color()
                self._update_lightbar_gradient()

                self._schedule_hardware_write(keys=True, lightbar=True)  # Full config load
                self._rebuild_tray_menu()
                self._save_last_config()  # Remember this choice
                self.status_bar.showMessage(f"Loaded config: {config_name}")

            except Exception as e:
                self.status_bar.showMessage(f"Failed to load config {config_name}: {e}")
    
    def _save_last_config(self):
        """Save the current config filename to .last_config file"""
        try:
            self.last_config_file.write_text(self.current_config_filename)
        except Exception as e:
            print(f"Warning: Could not save last config: {e}")
    
    @staticmethod
    def _slugify(name: str) -> str:
        """Convert a display name to a safe filename stem (lowercase, words joined by -)."""
        slug = name.lower()
        slug = re.sub(r"[^a-z0-9]+", "-", slug)
        slug = slug.strip("-") or "config"
        return slug

    def _new_config(self):
        """Create a new config file"""
        name, ok = QInputDialog.getText(
            self, "New Config", "Enter config name:", text="My Config"
        )
        if not ok or not name:
            return

        # Derive unique filename from name slug
        base_slug = self._slugify(name)
        new_path = self.config_dir / f"{base_slug}.json"
        suffix = 2
        while new_path.exists():
            new_path = self.config_dir / f"{base_slug}-{suffix}.json"
            suffix += 1

        new_config = self.manager.create_blank_config(name=name, all_black=True)
        self.manager.save_config(new_config, str(new_path))
        
        # Reload config list and select new one
        self._load_config_list()
        for i in range(self.config_combo.count()):
            if self.config_combo.itemData(i) == str(new_path):
                self.config_combo.setCurrentIndex(i)
                break
        
        self.status_bar.showMessage(f"Created new config: {new_path.name}")
    
    def _duplicate_config(self):
        """Duplicate the current config"""
        name, ok = QInputDialog.getText(
            self, "Duplicate Config", "Enter name for duplicate:",
            text=f"{self.current_config['name']} (copy)"
        )
        if not ok or not name:
            return

        # Derive unique filename from name slug
        base_slug = self._slugify(name)
        new_path = self.config_dir / f"{base_slug}.json"
        suffix = 2
        while new_path.exists():
            new_path = self.config_dir / f"{base_slug}-{suffix}.json"
            suffix += 1

        new_config = copy.deepcopy(self.current_config)
        new_config['name'] = name
        new_config.pop('description', None)

        self.manager.save_config(new_config, str(new_path))
        
        # Reload config list and select new one
        self._load_config_list()
        for i in range(self.config_combo.count()):
            if self.config_combo.itemData(i) == str(new_path):
                self.config_combo.setCurrentIndex(i)
                break
        
        self.status_bar.showMessage(f"Duplicated config: {new_path.name}")
    
    def _delete_config(self):
        """Delete the current config file"""
        # Count total configs
        config_files = [
            f for f in self.config_dir.glob("*.json") if f.name != "palette.json"
        ]
        
        if len(config_files) <= 1:
            QMessageBox.warning(
                self,
                "Cannot Delete",
                "Cannot delete the last remaining config.\n\nCreate another config first."
            )
            return
        
        reply = QMessageBox.question(
            self,
            "Delete Config?",
            f"Delete config '{self.current_config['name']}'?\n\nThis cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply != QMessageBox.StandardButton.Yes:
            return
        
        # Delete the file
        deleted_name = self.current_config['name']
        try:
            self.current_config_path.unlink()
        except Exception as e:
            QMessageBox.critical(
                self,
                "Error",
                f"Failed to delete config:\n{e}"
            )
            return
        
        # Reload config list
        self._load_config_list()
        
        # Explicitly load the first available config
        if self.config_combo.count() > 0:
            first_config_name = self.config_combo.itemText(0)
            self.config_combo.setCurrentIndex(0)
            # Force reload by calling _on_config_changed directly
            self._on_config_changed(first_config_name)
        
        self.status_bar.showMessage(f"Deleted config: {deleted_name}")
    
    def _rename_config(self):
        """Rename the current config"""
        current_name = self.current_config.get('name', 'Unnamed')
        new_name, ok = QInputDialog.getText(
            self,
            "Rename Config",
            "Enter new config name:",
            text=current_name
        )
        
        if not ok or not new_name or new_name == current_name:
            return
        
        # Update the name in the config dict
        old_name = self.current_config['name']
        self.current_config['name'] = new_name
        
        # Save the config with the new name
        try:
            self.manager.save_config(self.current_config, str(self.current_config_path))
        except Exception as e:
            QMessageBox.critical(
                self,
                "Error",
                f"Failed to rename config:\n{e}"
            )
            # Revert the change
            self.current_config['name'] = old_name
            return
        
        # Reload config list to update the display name
        self._load_config_list()
        self.status_bar.showMessage(f"Renamed config: '{old_name}' → '{new_name}'")
    
    def showEvent(self, event):
        """Handle window show event - fit keyboard in view"""
        super().showEvent(event)
        if hasattr(self, 'scene') and self.scene.sceneRect():
            self.view.fitInView(self.scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)
    
    def resizeEvent(self, event):
        """Handle window resize - refit keyboard in view"""
        super().resizeEvent(event)
        if hasattr(self, 'scene') and self.scene.sceneRect():
            self.view.fitInView(self.scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)


def _app_icon() -> QIcon:
    svg_path = os.path.join(os.path.dirname(__file__), "..", "assets", "icon.svg")
    if os.path.exists(svg_path):
        return QIcon(svg_path)
    return QIcon.fromTheme("input-keyboard")


def main():
    app = QApplication(sys.argv)
    app.setWindowIcon(_app_icon())
    app.setApplicationName("TUXEDO Keyboard Colors")
    app.setOrganizationName("TUXEDO")
    app.setQuitOnLastWindowClosed(False)
    app.setFont(QFont(FONT_FAMILY))

    settings = QSettings("TUXEDO", "KeyboardViewer")
    saved_theme = settings.value("theme", "dark")

    window = KeyboardViewerGUI()
    window._set_theme(saved_theme)

    def signal_handler(signum, frame):
        window._quit_app()

    signal.signal(signal.SIGINT, signal_handler)

    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
