"""
ui/widgets/scheduled_events_editor.py

Editor widget for Scheduled Events in the Creator Studio.
Allows creators to schedule world events at specific in-game minutes.
"""

import uuid
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QTableWidget,
    QTableWidgetItem, QHeaderView, QAbstractItemView, QLabel, QSpinBox
)
from workers.db_helpers import get_time_of_day_context

class ScheduledEventsEditorWidget(QWidget):
    """Widget for managing a list of scheduled world events."""
    
    changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._events: list[dict] = []
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        
        # Toolbar
        toolbar = QHBoxLayout()
        add_btn = QPushButton("Add Event")
        add_btn.clicked.connect(self._on_add_clicked)
        toolbar.addWidget(add_btn)
        
        self._status_label = QLabel("Events are global triggers that interrupt the narrator.")
        self._status_label.setStyleSheet("color: gray; font-style: italic;")
        toolbar.addSpacing(20)
        toolbar.addWidget(self._status_label)
        
        toolbar.addStretch()
        layout.addLayout(toolbar)
        
        # Table
        self._table = QTableWidget(0, 5)
        self._table.setHorizontalHeaderLabels(["Day", "Hour", "Minute", "Title / Preview", "Description"])
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self._table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Interactive)
        self._table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setAlternatingRowColors(True)
        
        # Context menu for deletion
        self._table.setContextMenuPolicy(Qt.CustomContextMenu)
        self._table.customContextMenuRequested.connect(self._show_context_menu)
        
        layout.addWidget(self._table)
        
    def set_events(self, events: list[dict]) -> None:
        """Populate the table with existing events."""
        self._events = events
        self._table.blockSignals(True)
        self._table.setRowCount(0)
        for event in sorted(events, key=lambda x: x.get("trigger_minute", 0)):
            self._add_row(event)
        self._table.blockSignals(False)

    def get_events(self) -> list[dict]:
        """Extract current events from the table."""
        events = []
        for row in range(self._table.rowCount()):
            day = int(self._table.cellWidget(row, 0).value())
            hour = int(self._table.cellWidget(row, 1).value())
            minute = int(self._table.cellWidget(row, 2).value())
            
            # Convert Day/Hour/Min to absolute minutes (Day 1 starts at 0)
            trigger_minute = ((day - 1) * 1440) + (hour * 60) + minute
            
            title = self._table.item(row, 3).text()
            description = self._table.item(row, 4).text()
            event_id = self._table.item(row, 3).data(Qt.UserRole) or str(uuid.uuid4())
            
            events.append({
                "event_id": event_id,
                "trigger_minute": trigger_minute,
                "title": title,
                "description": description
            })
        return events

    def _add_row(self, event: dict = None) -> None:
        row = self._table.rowCount()
        self._table.insertRow(row)
        
        trigger_min = event.get("trigger_minute", 0) if event else 0
        day = (trigger_min // 1440) + 1
        hour = (trigger_min % 1440) // 60
        minute = trigger_min % 60
        
        day_spin = QSpinBox()
        day_spin.setRange(1, 9999)
        day_spin.setValue(day)
        
        hour_spin = QSpinBox()
        hour_spin.setRange(0, 23)
        hour_spin.setValue(hour)
        
        min_spin = QSpinBox()
        min_spin.setRange(0, 59)
        min_spin.setValue(minute)
        
        def on_time_changed():
            self._update_preview(row)
            self.changed.emit()

        day_spin.valueChanged.connect(on_time_changed)
        hour_spin.valueChanged.connect(on_time_changed)
        min_spin.valueChanged.connect(on_time_changed)
        
        self._table.setCellWidget(row, 0, day_spin)
        self._table.setCellWidget(row, 1, hour_spin)
        self._table.setCellWidget(row, 2, min_spin)
        
        title_text = event.get("title", "New Event") if event else "New Event"
        title_item = QTableWidgetItem(title_text)
        title_item.setData(Qt.UserRole, event.get("event_id") if event else str(uuid.uuid4()))
        self._table.setItem(row, 3, title_item)
        
        desc_item = QTableWidgetItem(event.get("description", "") if event else "")
        self._table.setItem(row, 4, desc_item)
        
        self._update_preview(row)

    def _update_preview(self, row: int) -> None:
        day = int(self._table.cellWidget(row, 0).value())
        hour = int(self._table.cellWidget(row, 1).value())
        minute = int(self._table.cellWidget(row, 2).value())
        total_mins = ((day - 1) * 1440) + (hour * 60) + minute
        
        time_str = get_time_of_day_context(total_mins)
        title_item = self._table.item(row, 3)
        if title_item:
            title_text = title_item.text().split(" [")[0]
            title_item.setToolTip(f"Triggers at: {time_str}")

    def _on_add_clicked(self) -> None:
        self._add_row()
        self.changed.emit()

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        self.changed.emit()

    def _show_context_menu(self, pos) -> None:
        from PySide6.QtWidgets import QMenu
        menu = QMenu()
        delete_action = menu.addAction("Delete Event")
        duplicate_action = menu.addAction("Duplicate Event")
        
        action = menu.exec(self._table.viewport().mapToGlobal(pos))
        row = self._table.currentRow()
        if row < 0: return

        if action == delete_action:
            self._table.removeRow(row)
            self.changed.emit()
        elif action == duplicate_action:
            event = {
                "trigger_minute": ((int(self._table.cellWidget(row, 0).value()) - 1) * 1440) + 
                                  (int(self._table.cellWidget(row, 1).value()) * 60) + 
                                  int(self._table.cellWidget(row, 2).value()),
                "title": self._table.item(row, 3).text() + " (Copy)",
                "description": self._table.item(row, 4).text()
            }
            self._add_row(event)
            self.changed.emit()
