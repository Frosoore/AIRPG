"""
ui/widgets/map_editor.py

Hierarchical Map Editor for Axiom AI's Creator Studio.
Features a QTreeView for spatial hierarchy and a QGraphicsView for
visual node-link editing of distances at the current level.
"""

from __future__ import annotations

from typing import Any
import uuid

from PySide6.QtCore import Qt, QPointF, Signal, Slot, QRectF
from PySide6.QtGui import QBrush, QColor, QPen, QPainter, QStandardItemModel, QStandardItem
from PySide6.QtWidgets import (
    QGraphicsEllipseItem,
    QGraphicsItem,
    QGraphicsLineItem,
    QGraphicsScene,
    QGraphicsView,
    QGraphicsTextItem,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QDialog,
    QFormLayout,
    QSpinBox,
    QDialogButtonBox,
    QLabel,
    QMenu,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from core.localization import tr

SCALES = ["universe", "galaxy", "world", "country", "zone", "city", "district", "building", "room", "poi"]

# ---------------------------------------------------------------------------
# Graphics Items
# ---------------------------------------------------------------------------

class LocationNodeItem(QGraphicsEllipseItem):
    """Visual representation of a Location in the node editor."""
    
    def __init__(self, location_id: str, name: str, x: float, y: float, parent=None):
        super().__init__(-25, -25, 50, 50, parent)
        self.location_id = location_id
        self.name = name
        
        self.setPos(x, y)
        self.setFlag(QGraphicsItem.ItemIsMovable)
        self.setFlag(QGraphicsItem.ItemIsSelectable)
        self.setFlag(QGraphicsItem.ItemSendsGeometryChanges)
        
        self.setBrush(QBrush(QColor("#89b4fa")))
        self.setPen(QPen(QColor("#cdd6f4"), 2))
        
        self.label = QGraphicsTextItem(name, self)
        self.label.setDefaultTextColor(QColor("#cdd6f4"))
        self._update_label_pos()
        
        self.edges: list[ConnectionEdgeItem] = []

    def _update_label_pos(self):
        rect = self.label.boundingRect()
        self.label.setPos(-rect.width() / 2, 25)

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionHasChanged:
            for edge in self.edges:
                edge.update_position()
        return super().itemChange(change, value)

    def update_name(self, name: str):
        self.name = name
        self.label.setPlainText(name)
        self._update_label_pos()


class ConnectionEdgeItem(QGraphicsLineItem):
    """Visual representation of a distance-weighted link between locations."""
    
    def __init__(self, source: LocationNodeItem, target: LocationNodeItem, distance: int):
        super().__init__()
        self.source = source
        self.target = target
        self.distance = distance
        
        self.setPen(QPen(QColor("#585b70"), 2, Qt.DashLine))
        self.setZValue(-1)
        
        self.text_item = QGraphicsTextItem(f"{distance}m")
        self.text_item.setDefaultTextColor(QColor("#a6adc8"))
        
        source.edges.append(self)
        target.edges.append(self)
        self.update_position()

    def update_position(self):
        line = self.line()
        line.setP1(self.source.pos())
        line.setP2(self.target.pos())
        self.setLine(line)
        
        # Center the text
        mid = (self.source.pos() + self.target.pos()) / 2
        self.text_item.setPos(mid.x() - self.text_item.boundingRect().width() / 2,
                              mid.y() - self.text_item.boundingRect().height() / 2)

    def update_distance(self, distance: int):
        self.distance = distance
        self.text_item.setPlainText(f"{distance}m")
        self.update_position()


# ---------------------------------------------------------------------------
# Dialogs
# ---------------------------------------------------------------------------

class ScientificDistanceEntryDialog(QDialog):
    """Dialog to input distances with a power-of-10 helper for sci-fi scales."""
    def __init__(self, parent=None, initial_val=10):
        super().__init__(parent)
        self.setWindowTitle("Distance (km)")
        layout = QVBoxLayout(self)
        
        form = QFormLayout()
        self.base_spin = QSpinBox()
        self.base_spin.setRange(0, 999999)
        
        self.exp_spin = QSpinBox()
        self.exp_spin.setRange(0, 30)
        
        # Try to deduce exponent from initial_val
        if initial_val > 0:
            import math
            exp = int(math.log10(initial_val))
            if exp > 2: # Only use exponent if value is large
                self.exp_spin.setValue(exp)
                self.base_spin.setValue(int(initial_val / (10**exp)))
            else:
                self.exp_spin.setValue(0)
                self.base_spin.setValue(int(initial_val))
        else:
            self.base_spin.setValue(0)
            self.exp_spin.setValue(0)
            
        form.addRow("Base Value:", self.base_spin)
        form.addRow("Power of 10 (10^x):", self.exp_spin)
        layout.addLayout(form)
        
        self.preview = QLabel()
        self._update_preview()
        layout.addWidget(self.preview)
        
        self.base_spin.valueChanged.connect(self._update_preview)
        self.exp_spin.valueChanged.connect(self._update_preview)
        
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def _update_preview(self):
        try:
            val = self.base_spin.value() * (10 ** self.exp_spin.value())
            self.preview.setText(f"Result: {val:,} km")
        except OverflowError:
            self.preview.setText("Result: Too Large!")

    def get_value(self) -> int:
        return self.base_spin.value() * (10 ** self.exp_spin.value())


# ---------------------------------------------------------------------------
# MapEditorWidget
# ---------------------------------------------------------------------------

class MapEditorWidget(QWidget):
    """The main map editor tab."""
    
    data_changed = Signal()
    populate_requested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._locations: list[dict] = []
        self._connections: list[dict] = []
        self._selected_parent_id: str | None = None
        
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        
        splitter = QSplitter(Qt.Horizontal)
        
        # --- Left Pane: Hierarchy ---
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        
        header = QHBoxLayout()
        self._hierarchy_label = QLabel(tr("hierarchy"))
        header.addWidget(self._hierarchy_label)
        
        self._add_root_btn = QPushButton("+")
        self._add_root_btn.setToolTip(tr("add_location"))
        self._add_root_btn.setFixedWidth(40)
        self._add_root_btn.setStyleSheet("font-weight: bold; font-size: 14px;")
        header.addWidget(self._add_root_btn)
        left_layout.addLayout(header)
        
        self._tree = QTreeView()
        self._tree_model = QStandardItemModel()
        self._tree_model.setHorizontalHeaderLabels([tr("name"), "Scale"])
        self._tree.setModel(self._tree_model)
        self._tree.header().setSectionResizeMode(QHeaderView.Stretch)
        left_layout.addWidget(self._tree)
        
        splitter.addWidget(left_widget)
        
        # --- Right Pane: Node Editor ---
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        
        toolbar = QHBoxLayout()
        self._path_label = QLabel(f"{tr('editing_map_of')}: [Root]")
        toolbar.addWidget(self._path_label, 1)
        
        self._connect_btn = QPushButton(f"🔗 {tr('add_connection')}")
        self._connect_btn.setToolTip("Connect two selected nodes (Shortcut: C)")
        self._connect_btn.clicked.connect(self._add_connection)
        toolbar.addWidget(self._connect_btn)
        
        self._populate_btn = QPushButton(f"✨ {tr('populate')}")
        self._populate_btn.setToolTip("Automatically generate locations and connections via AI")
        self._populate_btn.clicked.connect(self._on_populate_clicked)
        toolbar.addWidget(self._populate_btn)
        
        right_layout.addLayout(toolbar)
        
        self._scene = QGraphicsScene()
        self._scene.setBackgroundBrush(QBrush(QColor("#181825")))
        self._view = QGraphicsView(self._scene)
        self._view.setRenderHint(QPainter.Antialiasing)
        self._view.setDragMode(QGraphicsView.RubberBandDrag)
        right_layout.addWidget(self._view)
        
        splitter.addWidget(right_widget)
        splitter.setStretchFactor(1, 3)
        layout.addWidget(splitter)
        
        # Connections
        self._tree.selectionModel().selectionChanged.connect(self._on_tree_selection_changed)
        self._add_root_btn.clicked.connect(self._on_add_root_clicked)
        self._scene.changed.connect(self._on_scene_changed)
        
        # Context Menu for Scene
        self._view.setContextMenuPolicy(Qt.CustomContextMenu)
        self._view.customContextMenuRequested.connect(self._show_scene_context_menu)
        
        # Context Menu for Tree
        self._tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._show_tree_context_menu)

    # ------------------------------------------------------------------
    # Data Population
    # ------------------------------------------------------------------

    def populate(self, locations: list[dict], connections: list[dict]):
        self._locations = locations
        self._connections = connections
        self._rebuild_tree()
        self._refresh_scene()

    def collect_data(self) -> tuple[list[dict], list[dict]]:
        # Sync current scene positions back to _locations
        for item in self._scene.items():
            if isinstance(item, LocationNodeItem):
                for loc in self._locations:
                    if loc["location_id"] == item.location_id:
                        loc["x"] = item.pos().x()
                        loc["y"] = item.pos().y()
                        break
        return self._locations, self._connections

    def _rebuild_tree(self):
        self._tree_model.clear()
        self._tree_model.setHorizontalHeaderLabels([tr("name"), "Scale"])
        
        # Map parent_id -> list of children
        children_map = {}
        roots = []
        for loc in self._locations:
            pid = loc.get("parent_id")
            if not pid:
                roots.append(loc)
            else:
                if pid not in children_map:
                    children_map[pid] = []
                children_map[pid].append(loc)
        
        def add_node(parent_item, loc):
            name_item = QStandardItem(loc["name"])
            name_item.setData(loc["location_id"], Qt.UserRole)
            
            scale_key = f"scale_{loc['scale']}"
            scale_item = QStandardItem(tr(scale_key) if scale_key in tr("ready") else loc["scale"])
            scale_item.setEditable(False)
            
            parent_item.appendRow([name_item, scale_item])
            
            for child in children_map.get(loc["location_id"], []):
                add_node(name_item, child)

        for root in roots:
            add_node(self._tree_model.invisibleRootItem(), root)
        
        self._tree.expandAll()

    def _refresh_scene(self):
        self._scene.clear()
        self._path_label.setText(f"{tr('editing_map_of')}: " + (self._get_location_name(self._selected_parent_id) or "[Root]"))
        
        # Find locations belonging to this parent
        filtered_locs = [l for l in self._locations if l.get("parent_id") == self._selected_parent_id]
        
        node_items = {}
        for loc in filtered_locs:
            item = LocationNodeItem(loc["location_id"], loc["name"], loc.get("x", 0), loc.get("y", 0))
            self._scene.addItem(item)
            node_items[loc["location_id"]] = item
            
        # Add connections between these locations
        loc_ids = {l["location_id"] for l in filtered_locs}
        for conn in self._connections:
            if conn["source_id"] in loc_ids and conn["target_id"] in loc_ids:
                src = node_items[conn["source_id"]]
                tgt = node_items[conn["target_id"]]
                edge = ConnectionEdgeItem(src, tgt, conn["distance_km"])
                self._scene.addItem(edge)
                self._scene.addItem(edge.text_item)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_C:
            self._add_connection()
        else:
            super().keyPressEvent(event)

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    @Slot()
    def _on_add_root_clicked(self):
        self._add_location(None, "universe")

    def _add_location(self, parent_id: str | None, scale: str):
        name, ok = QInputDialog.getText(self, tr("add_location"), tr("location_name"))
        if ok and name:
            new_id = str(uuid.uuid4())
            self._locations.append({
                "location_id": new_id,
                "name": name,
                "scale": scale,
                "parent_id": parent_id,
                "description": "",
                "x": 0, "y": 0
            })
            self._rebuild_tree()
            self._refresh_scene()
            self.data_changed.emit()

    def _delete_location(self, location_id: str):
        if not location_id:
            return
            
        # Recursive delete
        to_delete = {location_id}
        changed = True
        while changed:
            changed = False
            for l in self._locations:
                if l.get("parent_id") in to_delete and l["location_id"] not in to_delete:
                    to_delete.add(l["location_id"])
                    changed = True
        
        self._locations = [l for l in self._locations if l["location_id"] not in to_delete]
        self._connections = [c for c in self._connections if c["source_id"] not in to_delete and c["target_id"] not in to_delete]
        
        if self._selected_parent_id in to_delete:
            self._selected_parent_id = None
            
        self._rebuild_tree()
        self._refresh_scene()
        self.data_changed.emit()

    def _add_connection(self):
        # Simple selection-based connection
        selected = [i for i in self._scene.selectedItems() if isinstance(i, LocationNodeItem)]
        if len(selected) != 2:
            QMessageBox.information(self, tr("add_connection"), "Select exactly 2 nodes to connect.")
            return
        
        dlg = ScientificDistanceEntryDialog(self)
        if dlg.exec() == QDialog.Accepted:
            dist = dlg.get_value()
            # Add bidirectional connection for simplicity in RPG logic
            self._connections.append({"source_id": selected[0].location_id, "target_id": selected[1].location_id, "distance_km": dist})
            self._connections.append({"source_id": selected[1].location_id, "target_id": selected[0].location_id, "distance_km": dist})
            self._refresh_scene()
            self.data_changed.emit()

    @Slot()
    def _on_populate_clicked(self):
        text, ok = QInputDialog.getMultiLineText(self, tr("populate"), "Describe what kind of locations or regions to add (optional):")
        if ok:
            self.populate_requested.emit(text)

    # ------------------------------------------------------------------
    # Handlers
    # ------------------------------------------------------------------

    def _on_tree_selection_changed(self, selected, deselected):
        indexes = self._tree.selectionModel().selectedIndexes()
        if indexes:
            # Always fetch ID from the first column
            idx = indexes[0]
            if idx.column() != 0:
                idx = idx.siblingAtColumn(0)
            self._selected_parent_id = idx.data(Qt.UserRole)
        else:
            self._selected_parent_id = None
        self._refresh_scene()

    def _on_scene_changed(self, regions):
        # We don't emit data_changed on every tiny movement to avoid UI lag,
        # but we mark it as "dirty" if needed. For now, collect_data handles sync.
        pass

    def _show_scene_context_menu(self, pos):
        item = self._view.itemAt(pos)
        menu = QMenu()
        
        if isinstance(item, LocationNodeItem):
            view_act = menu.addAction("View Content")
            edit_act = menu.addAction(tr("edit_description"))
            del_act = menu.addAction(tr("delete"))
            
            action = menu.exec(self._view.mapToGlobal(pos))
            if action == view_act:
                self._enter_location(item.location_id)
            elif action == edit_act:
                self._edit_description(item.location_id)
            elif action == del_act:
                self._delete_location(item.location_id)
                
        elif isinstance(item, ConnectionEdgeItem):
            edit_dist = menu.addAction("Edit Distance")
            del_act = menu.addAction(tr("delete"))
            
            action = menu.exec(self._view.mapToGlobal(pos))
            if action == edit_dist:
                dlg = ScientificDistanceEntryDialog(self, item.distance)
                if dlg.exec() == QDialog.Accepted:
                    d = dlg.get_value()
                    # Update both directions
                    for c in self._connections:
                        if (c["source_id"] == item.source.location_id and c["target_id"] == item.target.location_id) or \
                           (c["source_id"] == item.target.location_id and c["target_id"] == item.source.location_id):
                            c["distance_km"] = d
                    self._refresh_scene()
                    self.data_changed.emit()
            elif action == del_act:
                self._connections = [c for c in self._connections 
                                     if not ((c["source_id"] == item.source.location_id and c["target_id"] == item.target.location_id) or
                                             (c["source_id"] == item.target.location_id and c["target_id"] == item.source.location_id))]
                self._refresh_scene()
                self.data_changed.emit()
        else:
            # Background click
            add_node = menu.addAction(tr("add_location"))
            
            action = menu.exec(self._view.mapToGlobal(pos))
            if action == add_node:
                # Deduce scale from parent
                parent_scale = self._get_location_scale(self._selected_parent_id)
                new_scale = self._get_next_scale(parent_scale)
                self._add_location(self._selected_parent_id, new_scale)

    def _show_tree_context_menu(self, pos):
        index = self._tree.indexAt(pos)
        menu = QMenu()
        
        if index.isValid():
            # Ensure we use column 0 for the ID
            if index.column() != 0:
                index = index.siblingAtColumn(0)
                
            loc_id = index.data(Qt.UserRole)
            if not loc_id: return
            
            add_child = menu.addAction("Add Child")
            del_act = menu.addAction(tr("delete"))
            
            action = menu.exec(self._tree.viewport().mapToGlobal(pos))
            if action == add_child:
                parent_scale = self._get_location_scale(loc_id)
                new_scale = self._get_next_scale(parent_scale)
                self._add_location(loc_id, new_scale)
            elif action == del_act:
                self._delete_location(loc_id)
        else:
            add_root = menu.addAction("Add Root Universe")
            if menu.exec(self._tree.viewport().mapToGlobal(pos)) == add_root:
                self._on_add_root_clicked()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _enter_location(self, location_id: str):
        """Programmatically select a node in the tree to view its children in the scene."""
        def find_item(parent_item, target_id):
            for r in range(parent_item.rowCount()):
                item = parent_item.child(r, 0)
                if item.data(Qt.UserRole) == target_id:
                    return item
                found = find_item(item, target_id)
                if found: return found
            return None
            
        item = find_item(self._tree_model.invisibleRootItem(), location_id)
        if item:
            self._tree.setCurrentIndex(item.index())
            self._tree.expand(item.index())

    def _get_location_name(self, loc_id: str | None) -> str | None:
        for l in self._locations:
            if l["location_id"] == loc_id:
                return l["name"]
        return None

    def _get_location_scale(self, loc_id: str | None) -> str | None:
        for l in self._locations:
            if l["location_id"] == loc_id:
                return l["scale"]
        return None

    def _get_next_scale(self, current_scale: str | None) -> str:
        if not current_scale: return "universe"
        try:
            idx = SCALES.index(current_scale)
            if idx + 1 < len(SCALES):
                return SCALES[idx + 1]
            return SCALES[-1]
        except ValueError:
            return "universe"

    def _edit_description(self, loc_id: str):
        loc = next((l for l in self._locations if l["location_id"] == loc_id), None)
        if loc:
            desc, ok = QInputDialog.getMultiLineText(self, tr("edit_description"), tr("description"), loc["description"])
            if ok:
                loc["description"] = desc
                self.data_changed.emit()

    def retranslate_ui(self):
        # Future-proofing for localization
        pass
