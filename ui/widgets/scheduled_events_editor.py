"""
ui/widgets/scheduled_events_editor.py

Visual editor for Scheduled Events and Custom Calendars in the Creator Studio.
Uses a spreadsheet-like grid for events and a form for calendar configuration.
"""

from __future__ import annotations

import uuid
import json
from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QTableWidget,
    QTableWidgetItem, QHeaderView, QAbstractItemView, QLabel, QSpinBox,
    QGroupBox, QFormLayout, QLineEdit, QSplitter
)
from core.time_system import CalendarConfig, TimeSystem
from core.localization import tr

class ScheduledEventsEditorWidget(QWidget):
    """Widget for managing world events and the universe's calendar."""
    
    changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._calendar = CalendarConfig()
        self._time_system = TimeSystem(self._calendar)
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        splitter = QSplitter(Qt.Vertical)

        # --- Top: Calendar Config ---
        self._cal_group = QGroupBox("Universe Calendar & Adventure Start")
        cal_layout = QHBoxLayout(self._cal_group)
        
        left_form = QFormLayout()
        self._mph_spin = QSpinBox()
        self._mph_spin.setRange(1, 9999)
        self._mph_spin.setValue(60)
        self._mph_spin.setToolTip("How many minutes are in one game hour")
        
        self._hpd_spin = QSpinBox()
        self._hpd_spin.setRange(1, 999)
        self._hpd_spin.setValue(24)
        self._hpd_spin.setToolTip("How many hours are in one game day")
        
        self._start_day_spin = QSpinBox()
        self._start_day_spin.setRange(1, 99999)
        self._start_day_spin.setValue(1)
        self._start_day_spin.setToolTip("The day on which the adventure begins")

        left_form.addRow("Minutes per Hour:", self._mph_spin)
        left_form.addRow("Hours per Day:", self._hpd_spin)
        left_form.addRow("Adventure Start Day:", self._start_day_spin)
        cal_layout.addLayout(left_form, 1)
        
        right_form = QFormLayout()
        self._month_edit = QLineEdit()
        self._month_edit.setPlaceholderText("Month 1, Month 2, ...")
        self._month_edit.setToolTip("Comma-separated list of month names (e.g., 'Aries, Taurus, ...')")
        
        self._preview_label = QLabel()
        self._preview_label.setStyleSheet("color: #89b4fa; font-weight: bold;")
        
        right_form.addRow("Month Names:", self._month_edit)
        right_form.addRow("Preview Start:", self._preview_label)
        cal_layout.addLayout(right_form, 2)

        # Connections
        for s in (self._mph_spin, self._hpd_spin, self._start_day_spin):
            s.valueChanged.connect(self._on_cal_changed)
        self._month_edit.textChanged.connect(self._on_cal_changed)
        
        # --- Bottom: Events Table ---
        bot_widget = QWidget()
        bot_layout = QVBoxLayout(bot_widget)
        bot_layout.setContentsMargins(0, 10, 0, 0)
        
        toolbar = QHBoxLayout()
        self._add_btn = QPushButton(f"{tr('add_event')} +")
        self._add_btn.setStyleSheet("background-color: #27ae60; font-weight: bold;")
        self._add_btn.setToolTip("Create a new scheduled world event (Enter)")
        self._add_btn.clicked.connect(self._on_add_clicked)
        toolbar.addWidget(self._add_btn)
        
        self._status_label = QLabel(tr("events_info"))
        self._status_label.setStyleSheet("color: gray; font-style: italic;")
        toolbar.addSpacing(20)
        toolbar.addWidget(self._status_label)
        toolbar.addStretch()
        bot_layout.addLayout(toolbar)
        # Events Table
        self._table = QTableWidget(0, 5)
        self._table.setHorizontalHeaderLabels([
            tr("day"), tr("hour"), tr("minute"), 
            tr("title_preview"), tr("description")
        ])
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self._table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self._table.setSelectionBehavior(QAbstractItemView.SelectItems)
        self._table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self._table.setAlternatingRowColors(True)
        self._table.itemChanged.connect(self._on_item_changed)
        bot_layout.addWidget(self._table)
        
        self._del_btn = QPushButton(tr("delete"))
        self._del_btn.setToolTip(f"{tr('delete_event_tooltip') if 'delete_event_tooltip' in tr('ready') else 'Remove selected events'} (Del)")
        self._del_btn.clicked.connect(self._on_delete_clicked)
        bot_layout.addWidget(self._del_btn)

        splitter.addWidget(self._cal_group)
        splitter.addWidget(bot_widget)
        splitter.setSizes([150, 450])
        layout.addWidget(splitter)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def retranslate_ui(self) -> None:
        self._cal_group.setTitle(tr("calendar_config") if "calendar_config" in tr("ready") else "Universe Calendar & Adventure Start")
        self._add_btn.setText(f"{tr('add_event')} +")
        self._status_label.setText(tr("events_info"))
        self._del_btn.setText(tr("delete"))
        self._table.setHorizontalHeaderLabels([
            tr("day"), tr("hour"), tr("minute"), 
            tr("title_preview"), tr("description")
        ])

    def set_events_and_calendar(self, events: list[dict], meta: dict) -> None:
        """Populate the UI with event and calendar data from Universe_Meta."""
        self._table.blockSignals(True)
        
        # Load Calendar
        cal_str = meta.get("calendar_config", "{}")
        self._calendar = CalendarConfig.from_json(cal_str)
        self._time_system = TimeSystem(self._calendar)
        
        self._mph_spin.setValue(self._calendar.minutes_per_hour)
        self._hpd_spin.setValue(self._calendar.hours_per_day)
        self._start_day_spin.setValue(self._calendar.start_day)
        self._month_edit.setText(", ".join(self._calendar.month_names))
        
        # Load Events
        self._table.setRowCount(0)
        for event in sorted(events, key=lambda x: x.get("trigger_minute", 0)):
            self._add_event_row(event)
            
        self._update_preview_all()
        self._table.blockSignals(False)

    def collect_data(self) -> tuple[list[dict], dict]:
        """Return (list of events, calendar metadata dict)."""
        # Calendar
        self._calendar.minutes_per_hour = self._mph_spin.value()
        self._calendar.hours_per_day = self._hpd_spin.value()
        self._calendar.start_day = self._start_day_spin.value()
        
        raw_months = self._month_edit.text().strip()
        if raw_months:
            self._calendar.month_names = [m.strip() for m in raw_months.split(",") if m.strip()]
        
        meta = {"calendar_config": self._calendar.to_json()}
        
        # Events
        events = []
        for row in range(self._table.rowCount()):
            day_w = self._table.cellWidget(row, 0)
            hour_w = self._table.cellWidget(row, 1)
            min_w = self._table.cellWidget(row, 2)
            
            if not day_w or not hour_w or not min_w: continue
            
            day = int(day_w.value())
            hour = int(hour_w.value())
            minute = int(min_w.value())
            
            # Use current time system to convert components to absolute mins
            trigger_min = self._time_system.components_to_minutes(day, hour, minute)
            
            it_title = self._table.item(row, 3)
            it_desc = self._table.item(row, 4)
            if not it_title or not it_desc: continue
            
            title = it_title.text()
            description = it_desc.text()
            event_id = it_title.data(Qt.UserRole) or str(uuid.uuid4())
            
            events.append({
                "event_id": event_id,
                "trigger_minute": trigger_min,
                "title": title,
                "description": description
            })
        return events, meta

    # ------------------------------------------------------------------
    # Implementation
    # ------------------------------------------------------------------

    def _add_event_row(self, event: dict | None = None) -> None:
        row = self._table.rowCount()
        self._table.insertRow(row)
        
        trigger_min = event.get("trigger_minute", 0) if event else 0
        day, hour, minute = self._time_system.minutes_to_components(trigger_min)
        
        day_spin = QSpinBox()
        day_spin.setRange(1, 99999)
        day_spin.setValue(day)
        
        hour_spin = QSpinBox()
        hour_spin.setRange(0, max(0, self._calendar.hours_per_day - 1))
        hour_spin.setValue(hour)
        
        min_spin = QSpinBox()
        min_spin.setRange(0, max(0, self._calendar.minutes_per_hour - 1))
        min_spin.setValue(minute)
        
        for s in (day_spin, hour_spin, min_spin):
            s.valueChanged.connect(lambda _: self._update_preview(row))
            s.valueChanged.connect(lambda _: self.changed.emit())
            
        self._table.setCellWidget(row, 0, day_spin)
        self._table.setCellWidget(row, 1, hour_spin)
        self._table.setCellWidget(row, 2, min_spin)
        
        title_text = event.get("title", tr("new_event")) if event else tr("new_event")
        it_title = QTableWidgetItem(title_text)
        it_title.setIcon(self.style().standardIcon(self.style().StandardPixmap.SP_FileDialogDetailedView))
        it_title.setData(Qt.UserRole, event.get("event_id") if event else str(uuid.uuid4()))
        
        it_desc = QTableWidgetItem(event.get("description", "") if event else "")
        
        self._table.setItem(row, 3, it_title)
        self._table.setItem(row, 4, it_desc)
        self._update_preview(row)

    def _update_preview(self, row: int) -> None:
        day_w = self._table.cellWidget(row, 0)
        hour_w = self._table.cellWidget(row, 1)
        min_w = self._table.cellWidget(row, 2)
        if not day_w or not hour_w or not min_w: return
        
        day = int(day_w.value())
        hour = int(hour_w.value())
        minute = int(min_w.value())
        
        total_mins = self._time_system.components_to_minutes(day, hour, minute)
        time_str = self._time_system.get_time_string(total_mins)
        
        it_title = self._table.item(row, 3)
        if it_title:
            it_title.setToolTip(f"{tr('triggers_at')} {time_str}")

    def _update_preview_all(self) -> None:
        for r in range(self._table.rowCount()):
            self._update_preview(r)
        self._preview_label.setText(self._time_system.get_time_string(0))

    @Slot()
    def _on_cal_changed(self) -> None:
        self._calendar.minutes_per_hour = self._mph_spin.value()
        self._calendar.hours_per_day = self._hpd_spin.value()
        self._calendar.start_day = self._start_day_spin.value()
        
        raw_months = self._month_edit.text().strip()
        if raw_months:
            self._calendar.month_names = [m.strip() for m in raw_months.split(",") if m.strip()]
        
        self._time_system = TimeSystem(self._calendar)
        
        # Update all spinbox ranges
        for r in range(self._table.rowCount()):
            h_spin = self._table.cellWidget(r, 1)
            m_spin = self._table.cellWidget(r, 2)
            if h_spin: h_spin.setRange(0, max(0, self._calendar.hours_per_day - 1))
            if m_spin: m_spin.setRange(0, max(0, self._calendar.minutes_per_hour - 1))
            self._update_preview(r)
        
        self._preview_label.setText(self._time_system.get_time_string(0))
        self.changed.emit()

    @Slot()
    def _on_add_clicked(self) -> None:
        self._add_event_row()
        self.changed.emit()

    @Slot()
    def _on_delete_clicked(self) -> None:
        indices = self._table.selectionModel().selectedRows()
        rows = sorted([i.row() for i in indices], reverse=True) if indices else [self._table.currentRow()]
        for r in rows:
            if 0 <= r < self._table.rowCount():
                self._table.removeRow(r)
        self.changed.emit()

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if self._table.signalsBlocked():
            return

        selected = self._table.selectedItems()
        if len(selected) > 1 and item in selected:
            self._table.blockSignals(True)
            new_text = item.text()
            col = item.column()
            for other in selected:
                if other != item and other.column() == col:
                    # Column 0,1,2 are spinboxes, so handle only 3 and 4
                    if other.column() >= 3:
                        other.setText(new_text)
            self._table.blockSignals(False)

        self.changed.emit()

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key_Delete:
            selected_items = self._table.selectedItems()
            if not selected_items:
                return

            rows = set()
            for item in selected_items:
                rows.add(item.row())

            is_full_row_delete = True
            for r in rows:
                for c in range(3, self._table.columnCount()): # Check only text cols
                    if self._table.item(r, c) not in selected_items:
                        is_full_row_delete = False
                        break
                if not is_full_row_delete: break
            
            if is_full_row_delete:
                self._on_delete_clicked()
            else:
                self._table.blockSignals(True)
                for item in selected_items:
                    item.setText("")
                self._table.blockSignals(False)
                self.changed.emit()
        elif event.key() == Qt.Key_Return or event.key() == Qt.Key_Enter:
            self._on_add_clicked()
        else:
            super().keyPressEvent(event)
