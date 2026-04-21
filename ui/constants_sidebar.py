"""
ui/constants_sidebar.py

Dynamic world-state sidebar for the Tabletop screen.

Displays all entity stats in real time, updated after every turn via
the refresh() slot which is connected to DbWorker.stats_loaded.

THREADING RULE: refresh() MUST only be called from the main thread via
the Signal/Slot mechanism.  Never call it directly from a worker thread.
"""

from __future__ import annotations

from PySide6.QtCore import Slot
from PySide6.QtWidgets import (
    QFormLayout,
    QGroupBox,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)
from core.localization import tr


class ConstantsSidebar(QWidget):
    """Live entity stats panel for the Tabletop screen.

    Updated via the refresh() slot which is connected to
    DbWorker.stats_loaded after every Arbitrator turn and rewind.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumWidth(200)
        self.setMaximumWidth(320)
        self._setup_ui()

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        from PySide6.QtWidgets import QTabWidget
        layout = QVBoxLayout(self)
        layout.setSpacing(4)
        layout.setContentsMargins(4, 4, 4, 4)

        self._header = QLabel(f"<b>{tr('tab_meta')}</b>")
        layout.addWidget(self._header)

        self._tabs = QTabWidget()
        
        # Stats Tab
        self._stats_scroll = QScrollArea()
        self._stats_scroll.setWidgetResizable(True)
        self._stats_content = QWidget()
        self._entities_layout = QVBoxLayout(self._stats_content)
        self._entities_layout.setSpacing(6)
        self._entities_layout.setContentsMargins(2, 2, 2, 2)
        self._entities_layout.addStretch()
        self._stats_scroll.setWidget(self._stats_content)
        
        # Inventory Tab
        self._inv_scroll = QScrollArea()
        self._inv_scroll.setWidgetResizable(True)
        self._inv_content = QWidget()
        self._inv_layout = QVBoxLayout(self._inv_content)
        self._inv_layout.setSpacing(6)
        self._inv_layout.setContentsMargins(2, 2, 2, 2)
        self._inv_layout.addStretch()
        self._inv_scroll.setWidget(self._inv_content)

        # Timeline Tab
        self._time_scroll = QScrollArea()
        self._time_scroll.setWidgetResizable(True)
        self._time_content = QWidget()
        self._time_layout = QVBoxLayout(self._time_content)
        self._time_layout.setSpacing(6)
        self._time_layout.setContentsMargins(2, 2, 2, 2)
        self._time_layout.addStretch()
        self._time_scroll.setWidget(self._time_content)

        self._tabs.addTab(self._stats_scroll, tr("stats"))
        self._tabs.addTab(self._inv_scroll, tr("inventory"))
        self._tabs.addTab(self._time_scroll, tr("timeline"))
        layout.addWidget(self._tabs)

    def retranslate_ui(self) -> None:
        """Refresh tab titles and header."""
        self._header.setText(f"<b>{tr('tab_meta')}</b>")
        self._tabs.setTabText(0, tr("stats"))
        self._tabs.setTabText(1, tr("inventory"))
        self._tabs.setTabText(2, tr("timeline"))

    @Slot(list)
    def refresh(self, entity_snapshots: list[dict]) -> None:
        """Rebuild the stats display from fresh entity snapshot data."""
        from core.localization import tr, fmt_num
        # Remove all existing widgets (except the trailing stretch)
        while self._entities_layout.count() > 1:
            item = self._entities_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not entity_snapshots:
            placeholder = QLabel(f"({tr('no_sessions')})")
            placeholder.setStyleSheet("color: gray;")
            self._entities_layout.insertWidget(0, placeholder)
            return

        for snap in entity_snapshots:
            if not isinstance(snap, dict):
                continue
            entity_id: str = snap.get("entity_id", "unknown")
            name: str = snap.get("name", entity_id)
            entity_type: str = snap.get("entity_type", "")
            stats: dict = snap.get("stats") or {} 

            group_title = f"{name}"
            if entity_type:
                # Localize entity type
                translated_type = tr(f"entity_{entity_type}")
                # Use localized spacing
                from core.config import load_config
                lang = getattr(load_config(), "language", "en")
                if lang in ("zh", "ja", "ko"):
                    group_title += f"[{translated_type}]"
                else:
                    group_title += f" [{translated_type}]"
            group = QGroupBox(group_title)
            group.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            form = QFormLayout(group)
            form.setSpacing(2)

            if stats:
                for stat_key, stat_value in stats.items():
                    # Use stat_fmt if available
                    label_text = tr("stat_fmt", key=stat_key, val="").rstrip(":").rstrip(" :").rstrip("：")
                    from core.config import load_config
                    lang = getattr(load_config(), "language", "en")
                    colon = "：" if lang in ("zh", "ja") else ":"
                    if lang == "fr": colon = " :"
                    
                    key_label = QLabel(label_text + colon)
                    key_label.setStyleSheet("font-size: 11px;")
                    val_label = QLabel(fmt_num(stat_value))
                    val_label.setStyleSheet("font-size: 11px; font-weight: bold;")
                    form.addRow(key_label, val_label)
            else:
                form.addRow(QLabel(f"({tr('no_sessions')})"))

            # Insert before the trailing stretch
            insert_idx = max(0, self._entities_layout.count() - 1)
            self._entities_layout.insertWidget(insert_idx, group)

    @Slot(dict)
    def refresh_inventory(self, inventory_data: dict) -> None:
        """Rebuild the inventory display."""
        # Remove all existing widgets (except the trailing stretch)
        while self._inv_layout.count() > 1:
            item = self._inv_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not inventory_data:
            placeholder = QLabel(f"({tr('no_sessions')})")
            placeholder.setStyleSheet("color: gray;")
            self._inv_layout.insertWidget(0, placeholder)
            return

        for entity_id, items in inventory_data.items():
            if not items:
                continue
                
            group = QGroupBox(f"{entity_id}")
            group.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            form = QFormLayout(group)
            form.setSpacing(2)

            for item in items:
                name = item.get("name", "Unknown")
                qty = item.get("quantity", 1)
                rarity = item.get("rarity", "common")
                
                # Simple color-coding for rarity
                rarity_colors = {
                    "common": "white",
                    "rare": "#4fa3ff",
                    "epic": "#a335ee",
                    "legendary": "#ff8000"
                }
                color = rarity_colors.get(rarity.lower(), "white")
                
                name_label = QLabel(f"<b>{name}</b>")
                name_label.setStyleSheet(f"color: {color}; font-size: 11px;")
                qty_label = QLabel(f"x{qty}")
                qty_label.setStyleSheet("font-size: 11px;")
                
                form.addRow(name_label, qty_label)

            insert_idx = max(0, self._inv_layout.count() - 1)
            self._inv_layout.insertWidget(insert_idx, group)

    @Slot(list)
    def refresh_timeline(self, timeline_events: list[dict]) -> None:
        """Rebuild the timeline display."""
        # Remove all existing widgets (except the trailing stretch)
        while self._time_layout.count() > 1:
            item = self._time_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not timeline_events:
            placeholder = QLabel(f"({tr('no_sessions')})")
            placeholder.setStyleSheet("color: gray;")
            self._time_layout.insertWidget(0, placeholder)
            return

        from workers.db_helpers import get_time_of_day_context
        for event in timeline_events:
            time_str = get_time_of_day_context(event.get("in_game_time", 0))
            turn_id = event.get("turn_id", 0)
            desc = event.get("description", "")
            
            turn_part = tr("turn_fmt", count=turn_id)
            group = QGroupBox(f"{turn_part} - {time_str}")
            group.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            vbox = QVBoxLayout(group)
            
            text_label = QLabel(desc)
            text_label.setWordWrap(True)
            text_label.setStyleSheet("font-size: 11px;")
            vbox.addWidget(text_label)

            insert_idx = max(0, self._time_layout.count() - 1)
            self._time_layout.insertWidget(insert_idx, group)
