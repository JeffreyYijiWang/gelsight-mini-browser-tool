"""Qt Widgets and native OpenGL only: no HTML, HTTP server, or WebEngine."""
from __future__ import annotations
import json
import os
from pathlib import Path
import threading
import time
from uuid import uuid4
import cv2
import numpy as np
from PIL import Image
from PySide6.QtCore import Qt, QThread, Signal, QTimer, QUrl, QLockFile
from PySide6.QtGui import QImage, QPixmap, QIcon, QDesktopServices, QVector3D
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QComboBox, QSplitter, QTabWidget, QTableWidget, QTableWidgetItem, QScrollArea,
    QProgressBar, QMessageBox, QFileDialog, QDoubleSpinBox, QSlider, QGroupBox, QFormLayout)
from PySide6.QtMultimedia import QCamera, QMediaDevices, QMediaCaptureSession, QVideoSink
import pyqtgraph.opengl as gl
from pyqtgraph.opengl.shaders import ShaderProgram, VertexShader, FragmentShader
from .project import Project, export_print, surface_mesh, display_depth
from .reconstruction import CONFIG
from .camera import discover, DirectShowCamera


RELIEF_SHADER = ShaderProgram('gelsight-relief', [
    VertexShader('''varying vec3 n; void main() {
        n = normalize(gl_NormalMatrix * gl_Normal);
        gl_FrontColor = gl_Color; gl_BackColor = gl_Color;
        gl_Position = ftransform(); }'''),
    FragmentShader('''varying vec3 n; void main() {
        vec3 normal = normalize(n);
        float diffuse = max(0., dot(normal, normalize(vec3(-.4, .6, 1.))));
        float rim = pow(1. - abs(normal.z), 3.);
        gl_FragColor = vec4(gl_Color.rgb * (.42 + .58 * diffuse) + .08 * rim, gl_Color.a);
    }''')])


def qimage(rgb):
    a = np.ascontiguousarray(rgb, dtype=np.uint8)
    return QImage(a.data, a.shape[1], a.shape[0], a.strides[0], QImage.Format.Format_RGB888).copy()


class Job(QThread):
    result = Signal(object)
    failed = Signal(str)
    progress = Signal(int, str)

    def __init__(self, operation):
        super().__init__(); self.operation = operation; self.cancelled = threading.Event()

    def run(self):
        def progress(value, text):
            if self.cancelled.is_set(): raise InterruptedError('Operation cancelled; completed captures are preserved.')
            self.progress.emit(round(value*100), text)
        try: self.result.emit(self.operation(progress))
        except Exception as exc: self.failed.emit(f'{type(exc).__name__}: {exc}')


class Window(QMainWindow):
    def __init__(self, directory=None):
        super().__init__()
        self.setWindowTitle('GelSight Matrix Studio — native desktop')
        self.resize(1400, 930)
        self.project = None; self.lock = None; self.job = None
        self.camera = None; self.latest = None; self.last_frame_time = 0.; self.calibration = None
        self.calibration_frames = None; self.frame_number = 0; self.last_captured_frame = -1
        self.selected = None; self.z = None; self.rgb = None; self.preview_item = None
        self.session = QMediaCaptureSession(self); self.sink = QVideoSink(self)
        self.session.setVideoSink(self.sink); self.sink.videoFrameChanged.connect(self.on_frame)
        self.media = QMediaDevices(self); self.media.videoInputsChanged.connect(self.refresh_devices)
        central = QWidget(); self.setCentralWidget(central); outer = QVBoxLayout(central)
        title = QLabel('GELSIGHT  /  MATRIX STUDIO'); title.setStyleSheet('font-size:24px;font-weight:700;color:#a9e5d0')
        outer.addWidget(title)
        self.project_label = QLabel(); outer.addWidget(self.project_label)
        split = QSplitter(); outer.addWidget(split, 1)
        controls = QWidget(); layout = QVBoxLayout(controls)
        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setWidget(controls); scroll.setFixedWidth(340)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff); split.addWidget(scroll)
        self.actions = []
        def button(text, callback, parent=layout):
            b = QPushButton(text); b.clicked.connect(callback); parent.addWidget(b); self.actions.append(b); return b
        button('New / open project folder…', self.choose_project)
        group = QGroupBox('1  ·  Configure & calibrate'); form = QVBoxLayout(group); layout.addWidget(group)
        self.devices = QComboBox(); self.devices.currentIndexChanged.connect(self.device_selected); form.addWidget(self.devices)
        self.resolutions = QComboBox(); form.addWidget(self.resolutions)
        self.resolutions.currentIndexChanged.connect(self.resolution_selected)
        button('Refresh GelSight devices', self.refresh_devices, form)
        button('Connect camera', self.connect_camera, form)
        button('Disconnect camera', self.stop_camera, form)
        config = QLabel('Mini FP32 model · 320 × 240 surface\n10% removed from each edge, once\n50-frame untouched-gel baseline\nGolan DCT recipe · λ = 0.0005\nRelative depth · no physical scale')
        config.setWordWrap(True); form.addWidget(config)
        button('View configuration comparison', self.show_configuration, form)
        button('Calibrate — gel must be untouched', self.begin_calibration, form)
        self.calibration_label = QLabel('Calibration required'); form.addWidget(self.calibration_label)
        group = QGroupBox('2  ·  Capture the matrix'); form = QVBoxLayout(group); layout.addWidget(group)
        self.position_label = QLabel(); form.addWidget(self.position_label)
        self.capture_button = button('Capture cell  →', self.capture, form)
        self.row_button = button('Next row  ↙  (column 0)', self.next_row, form)
        hint = QLabel('Move right with overlap for each cell.\nReturn to the left for the next row.\nRows may have different lengths.'); hint.setWordWrap(True); form.addWidget(hint)
        group = QGroupBox('3  ·  Assemble & print'); form = QVBoxLayout(group); layout.addWidget(group)
        self.overlap = QDoubleSpinBox(); self.overlap.setRange(10, 60); self.overlap.setValue(25); self.overlap.setSuffix('% expected overlap'); form.addWidget(self.overlap)
        button('Build continuous panorama', self.assemble, form)
        warning = QLabel('Blended seams and missing cells are synthetic.\nWhite in Synthetic mask identifies altered areas.'); warning.setWordWrap(True); form.addWidget(warning)
        self.width_mm = QDoubleSpinBox(); self.width_mm.setRange(1, 1000); self.width_mm.setValue(100); self.width_mm.setSuffix(' mm print width'); form.addWidget(self.width_mm)
        self.base_mm = QDoubleSpinBox(); self.base_mm.setRange(.5, 50); self.base_mm.setValue(2); self.base_mm.setSuffix(' mm backing'); form.addWidget(self.base_mm)
        self.relief_label = QLabel(); form.addWidget(self.relief_label)
        self.relief = QSlider(Qt.Orientation.Horizontal); self.relief.setRange(0, 500); self.relief.setValue(20); form.addWidget(self.relief)
        self.render_timer = QTimer(self); self.render_timer.setSingleShot(True); self.render_timer.timeout.connect(self.render_3d)
        self.relief.valueChanged.connect(self.schedule_render); self.width_mm.valueChanged.connect(self.schedule_render)
        button('Export full-resolution STL solid', self.print_surface, form)
        button('Open selected output folder', self.open_output, form)
        layout.addStretch()
        right = QWidget(); right_layout = QVBoxLayout(right); split.addWidget(right)
        self.tabs = QTabWidget(); right_layout.addWidget(self.tabs, 3)
        images = QWidget(); image_layout = QVBoxLayout(images)
        self.image_mode = QComboBox(); self.image_mode.addItems(['RGB', 'Depth', 'Normal', 'Background subtracted', 'Synthetic mask', 'Observed mask']); image_layout.addWidget(self.image_mode)
        self.image_mode.currentTextChanged.connect(self.render_image)
        self.image_view = QLabel('Connect the named GelSight Mini to begin.'); self.image_view.setAlignment(Qt.AlignmentFlag.AlignCenter); self.image_view.setMinimumSize(480, 320); image_layout.addWidget(self.image_view, 1)
        self.tabs.addTab(images, 'Captured maps')
        view_widget = QWidget(); view_layout = QVBoxLayout(view_widget)
        self.view_mode = QComboBox(); self.view_mode.addItems(['Relief mesh', 'Point cloud', 'Baked normal lighting (flat plane)']); self.view_mode.currentIndexChanged.connect(self.schedule_render); view_layout.addWidget(self.view_mode)
        self.view = gl.GLViewWidget(); self.view.setBackgroundColor('#172322'); view_layout.addWidget(self.view, 1)
        fit = QPushButton('Fit surface in view'); fit.clicked.connect(self.fit_view); view_layout.addWidget(fit)
        view_layout.addWidget(QLabel('Drag to orbit · wheel to zoom · preview reduced to ≤160 × 160; exports retain every depth sample.'))
        self.tabs.addTab(view_widget, 'Native 3D viewport')
        self.live_tab = QWidget(); live_layout = QVBoxLayout(self.live_tab)
        self.live_status = QLabel('Connect the named GelSight Mini to see its current image.')
        self.live_status.setWordWrap(True); live_layout.addWidget(self.live_status)
        self.live_view = QLabel('Camera disconnected'); self.live_view.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.live_view.setMinimumSize(480, 320); live_layout.addWidget(self.live_view, 1)
        live_hint = QLabel('Current RGB before the 10% edge crop. Capture cell saves this frame and its surface outputs. Saved images remain in Captured maps.')
        live_hint.setWordWrap(True); live_layout.addWidget(live_hint)
        self.tabs.addTab(self.live_tab, 'Live GelSight')
        self.tabs.setCurrentWidget(self.live_tab)
        self.tabs.currentChanged.connect(lambda index:QTimer.singleShot(0, self.fit_view) if index==1 else None)
        self.result_label = QLabel('Captured geometry and maps appear here. No samples are published.'); self.result_label.setWordWrap(True); right_layout.addWidget(self.result_label)
        self.table = QTableWidget(); self.table.setMinimumHeight(180); self.table.cellClicked.connect(self.select_cell); right_layout.addWidget(self.table, 1)
        self.assemblies = QComboBox(); self.assemblies.currentIndexChanged.connect(self.select_assembly); right_layout.addWidget(self.assemblies)
        footer = QHBoxLayout(); outer.addLayout(footer)
        self.status = QLabel('Ready'); self.status.setWordWrap(True); footer.addWidget(self.status, 1)
        self.progress = QProgressBar(); self.progress.setMaximumWidth(220); footer.addWidget(self.progress)
        self.cancel_button = QPushButton('Cancel work'); self.cancel_button.clicked.connect(self.cancel); footer.addWidget(self.cancel_button)
        self.setStyleSheet('QMainWindow,QWidget{background:#202b2a;color:#e4ece7;font-size:12px} QGroupBox{border:1px solid #53645e;margin-top:12px;padding-top:12px} QGroupBox::title{color:#b7dacb} QPushButton,QComboBox,QDoubleSpinBox{padding:6px;background:#354741;border:1px solid #647a70;border-radius:4px} QPushButton:hover{background:#49645a} QPushButton:disabled{color:#71847a} QTableWidget{background:#18221f} QProgressBar::chunk{background:#83b79f}')
        self.open_project(directory or Path(__file__).resolve().parents[1]/'desktop-data'/('collection-'+time.strftime('%Y%m%d-%H%M%S')+'-'+uuid4().hex[:6]))
        self.refresh_devices(); self.schedule_render()
        self.watchdog = QTimer(self); self.watchdog.timeout.connect(self.check_camera); self.watchdog.start(1000)
        available = QApplication.primaryScreen().availableGeometry()
        self.resize(min(1400, int(available.width()*.95)), min(930, int(available.height()*.92)))
        self.set_busy(False)

    def error(self, message):
        self.status.setText(message); QMessageBox.warning(self, 'GelSight Matrix Studio', message)

    def show_configuration(self):
        QMessageBox.information(self, 'Golan configuration comparison',
            'Uses the bundled Mini FP32 weights and Golan core feature order B,G,R,y/h,x/w, marker threshold 70, gradient cap 50, and DCT boundary/frequency recipe (λ 0.0005).\n\n'
            'Full 320×240 inference is used for each frozen capture. The p5 default uses half-resolution inference and temporal smoothing (alpha 0.6); neither is used here. CPU bilinear resizing can differ from browser/WebGL resizing.\n\n'
            'Your requested crop is 10% per edge (upstream default: 15%). RGB, depth, normals, mesh and points share the cropped field.\n\n'
            'Calibration averages 50 explicitly untouched, distinct delivered frames. It subtracts the baseline; it does not establish physical units or constitute approval by Golan Levin.')

    def choose_project(self):
        folder = QFileDialog.getExistingDirectory(self, 'Choose a new or existing native project folder')
        if folder: self.open_project(folder)

    def open_project(self, folder):
        try:
            Path(folder).mkdir(parents=True, exist_ok=True)
            lock = QLockFile(str(Path(folder)/'.desktop.lock')); lock.setStaleLockTime(0)
            if not lock.tryLock(0): raise ValueError('This project is already open in another application window.')
            project = Project(folder)
        except Exception as exc: self.error(str(exc)); return
        if self.lock: self.lock.unlock()
        self.lock = lock; self.project = project; self.calibration = None; self.selected = None; self.z = None
        self.project_label.setText(str(project.root)); self.calibration_label.setText('Calibration required for this camera session')
        self.refresh_matrix()

    def refresh_devices(self):
        if self.camera: self.stop_camera()
        self.devices.blockSignals(True); self.devices.clear()
        self.available_devices = [d for d in QMediaDevices.videoInputs() if 'gelsight' in d.description().lower()]
        for d in self.available_devices: self.devices.addItem(d.description(), d)
        if not self.available_devices:
            try:
                for d in discover(): self.devices.addItem(d['name']+' · DirectShow', d)
            except Exception as exc: self.status.setText('Native camera probe failed: '+str(exc))
        self.devices.blockSignals(False); self.device_selected()
        if not self.devices.count(): self.status.setText('No named GelSight detected. Connect its USB cable, then Refresh. Other webcams are never selected.')

    def device_selected(self, *_):
        self.stop_camera(); self.resolutions.blockSignals(True); self.resolutions.clear()
        device = self.devices.currentData()
        if isinstance(device, dict):
            for size in [(640, 480), (1280, 960)]: self.resolutions.addItem(f'{size[0]} × {size[1]} delivered RGB (native {device["mode"]["width"]} × {device["mode"]["height"]})', size)
        elif device:
            formats = [f for f in device.videoFormats() if 320<=f.resolution().width()<=1280 and 240<=f.resolution().height()<=960 and f.maxFrameRate()>0]
            formats.sort(key=lambda f:(abs(f.resolution().width()-640), abs(f.maxFrameRate()-30)))
            seen = set()
            for f in formats:
                key = (f.resolution().width(), f.resolution().height())
                if key in seen: continue
                seen.add(key); self.resolutions.addItem(f'{key[0]} × {key[1]} · {f.maxFrameRate():g} fps', f)
        self.resolutions.blockSignals(False)

    def resolution_selected(self, *_): self.stop_camera()

    def connect_camera(self):
        device = self.devices.currentData(); fmt = self.resolutions.currentData()
        if device is None or fmt is None: return self.error('No supported named Mini format. Reconnect USB and refresh. Maximum camera size: 1280×960.')
        self.stop_camera()
        if isinstance(device, dict):
            self.camera = DirectShowCamera(device, fmt, self)
            self.camera.frame.connect(self.accept_rgb)
            self.camera.error.connect(lambda text:self.status.setText('Camera error: '+text))
        else:
            self.camera = QCamera(device, self)
            self.camera.setCameraFormat(fmt); self.camera.errorOccurred.connect(lambda *args:self.status.setText('Camera error: '+self.camera.errorString() if self.camera else 'Camera stopped'))
            self.session.setCamera(self.camera)
        self.camera.start(); self.last_frame_time = time.monotonic()
        self.status.setText('Opening named Mini…'); self.live_status.setText('Connecting to the named Mini…')
        self.live_view.setText('Waiting for camera frames…'); self.tabs.setCurrentWidget(self.live_tab)

    def stop_camera(self):
        if self.camera:
            self.camera.stop(); self.session.setCamera(None); self.camera.deleteLater(); self.camera = None
        self.latest = None; self.calibration = None; self.calibration_frames = None
        if hasattr(self, 'live_view'):
            self.live_view.setText('Camera disconnected')
            self.live_status.setText('Connect the named GelSight Mini to see its current image.')
        if hasattr(self, 'calibration_label'): self.calibration_label.setText('Calibration required')

    def check_camera(self):
        if self.camera and time.monotonic()-self.last_frame_time>8:
            self.stop_camera(); self.set_busy(self.job is not None)
            self.status.setText('No Mini frames received. Close any browser camera feed, check Windows Camera privacy access, reconnect USB, then Connect again.')

    def on_frame(self, frame):
        if not frame.isValid(): return
        image = frame.toImage().convertToFormat(QImage.Format.Format_RGB888)
        if image.isNull(): return
        raw = np.frombuffer(image.constBits(), np.uint8).reshape(image.height(), image.bytesPerLine())[:, :image.width()*3].reshape(image.height(), image.width(), 3).copy()
        self.accept_rgb(raw)

    def accept_rgb(self, raw):
        first = self.latest is None
        self.latest = raw; self.frame_number += 1; self.last_frame_time = time.monotonic()
        if first: self.status.setText(f'Mini streaming · {raw.shape[1]} × {raw.shape[0]} delivered RGB · calibrate untouched gel to begin')
        self.live_view.setPixmap(QPixmap.fromImage(qimage(raw)).scaled(self.live_view.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        if first: self.live_status.setText(f'Live GelSight RGB · {raw.shape[1]} × {raw.shape[0]} · updates independently of saved captures')
        if self.calibration_frames is not None:
            self.calibration_frames.append(raw)
            self.status.setText(f'Keep gel untouched · collecting {len(self.calibration_frames)}/50 distinct frames')
            if len(self.calibration_frames)==50:
                frames = self.calibration_frames; self.calibration_frames = None
                device = self.device_key()
                self.run_job(lambda progress:self.project.calibrate(frames, device, progress), self.calibrated)

    def device_key(self):
        d = self.devices.currentData()
        if isinstance(d, dict): return json.dumps(d, sort_keys=True)
        return d.description()+' | '+bytes(d.id()).hex() if d else ''

    def begin_calibration(self):
        if self.latest is None or not self.camera: return self.error('Connect the Mini and wait for live RGB first.')
        self.calibration = None; self.calibration_frames = []; self.set_busy(True)
        self.status.setText('Collecting 50 fresh frames. Keep the gel untouched.')

    def calibrated(self, record):
        self.calibration = record; self.calibration_label.setText('Untouched baseline saved · relative relief')
        self.status.setText('Calibrated. Place the first surface, then Capture cell.')

    def capture(self):
        if self.latest is None or self.calibration is None: return self.error('Connect and calibrate the untouched Mini first.')
        if self.frame_number==self.last_captured_frame or time.monotonic()-self.last_frame_time>2:
            return self.error('Wait for a fresh camera frame before capturing again.')
        raw = self.latest.copy(); calibration = self.calibration; device = self.device_key()
        self.last_captured_frame = self.frame_number
        self.run_job(lambda progress:self.project.capture(raw, calibration, device, progress), self.saved_surface)

    def next_row(self):
        try: self.project.new_row(); self.refresh_matrix()
        except Exception as exc: self.error(str(exc))

    def refresh_matrix(self):
        rows = self.project.data['rows']; self.table.clear(); self.table.setRowCount(len(rows))
        columns = max(1, max(map(len, rows))); self.table.setColumnCount(columns)
        self.table.setHorizontalHeaderLabels([f'Column {i}' for i in range(columns)])
        self.table.setVerticalHeaderLabels([f'Row {i}' for i in range(len(rows))])
        self.table.setIconSize(__import__('PySide6.QtCore', fromlist=['QSize']).QSize(88, 66))
        for row, cells in enumerate(rows):
            self.table.setRowHeight(row, 86)
            for col, record in enumerate(cells):
                item = QTableWidgetItem(QIcon(str(self.project.root/'captures'/record['id']/'rgb.png')), f'{row},{col}')
                item.setFlags(Qt.ItemFlag.ItemIsEnabled|Qt.ItemFlag.ItemIsSelectable); self.table.setItem(row, col, item)
        self.position_label.setText(f'Next capture: row {len(rows)-1}, column {len(rows[-1])}')
        self.assemblies.blockSignals(True); self.assemblies.clear(); self.assemblies.addItem('Select a saved panorama…', None)
        for i, record in enumerate(self.project.data['assemblies']): self.assemblies.addItem(f'Panorama {i+1} · {record["output_size"]} · synthetic assembly', record['id'])
        self.assemblies.blockSignals(False)

    def select_cell(self, row, col):
        if col<len(self.project.data['rows'][row]): self.load_surface(self.project.root/'captures'/self.project.data['rows'][row][col]['id'])

    def select_assembly(self, *_):
        identifier = self.assemblies.currentData()
        if identifier: self.load_surface(self.project.root/'assemblies'/identifier)

    def assemble(self):
        overlap = self.overlap.value()/100
        self.run_job(lambda progress:self.project.assemble(overlap, progress), self.saved_surface)

    def saved_surface(self, folder):
        self.refresh_matrix(); self.load_surface(folder); self.status.setText('Saved: '+str(folder))

    def load_surface(self, folder):
        try:
            self.z = np.load(folder/'depth.npy', allow_pickle=False); self.rgb = np.asarray(Image.open(folder/'rgb.png').convert('RGB'))
            self.selected = folder; self.image_mode.setCurrentText('RGB'); self.render_image(); self.schedule_render()
            if (folder/'assembly.json').exists():
                report = json.loads((folder/'assembly.json').read_text()); accepted = sum(l['accepted'] for l in report['neighbors'])
                self.result_label.setText(f'Artistic panorama · {accepted}/{len(report["neighbors"])} neighbor matches accepted · {report["missing_fraction"]:.1%} missing-area fill · {report["synthetic_fraction"]:.1%} synthetic influence. Relative geometry, not metric.')
            else: self.result_label.setText('Synchronized capture: RGB · float depth · normals · surface mesh · point cloud. Relative geometry.')
        except Exception as exc: self.error(str(exc))

    def render_image(self, *_):
        mode = self.image_mode.currentText()
        if self.selected is None: self.image_view.setText('Select a saved capture or panorama.'); return
        name = {'RGB':'rgb.png', 'Depth':'depth.png', 'Normal':'normal.png', 'Background subtracted':'background-subtracted.png', 'Synthetic mask':'synthetic-mask.png', 'Observed mask':'observed-mask.png'}[mode]
        path = self.selected/name
        if not path.exists(): self.image_view.setText('This map is not available for the selected item.'); return
        image = Image.open(path)
        if image.mode=='RGBA':
            background = Image.new('RGBA', image.size, '#57645d'); background.alpha_composite(image); image = background
        self.show_image(np.asarray(image.convert('RGB')))

    def show_image(self, rgb):
        self.image_view.setPixmap(QPixmap.fromImage(qimage(rgb)).scaled(self.image_view.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))

    def schedule_render(self, *_):
        self.relief_label.setText(f'Relief range: {self.relief.value()/10:.1f} mm (authored)')
        self.render_timer.start(80)

    def render_3d(self):
        if self.z is None: return
        if self.preview_item is not None: self.view.removeItem(self.preview_item)
        h, w = self.z.shape; factor = min(1, 160/max(h, w)); size = (max(2, round(w*factor)), max(2, round(h*factor)))
        height = cv2.resize(self.z, size); colors = cv2.resize(self.rgb, size).astype(float)/255
        scaled = (height-self.z.min())/max(float(np.ptp(self.z)), 1e-12)*(self.relief.value()/10)
        mesh = surface_mesh(scaled, spacing=self.width_mm.value()/(size[0]-1))
        vertices = mesh.vertices.copy(); vertices[:, :2] -= vertices[:, :2].mean(axis=0)
        rgba = np.concatenate((colors.reshape(-1, 3), np.ones((height.size, 1))), axis=1)
        mode = self.view_mode.currentIndex()
        if mode==1:
            self.preview_item = gl.GLScatterPlotItem(pos=vertices, color=rgba, size=2, pxMode=True)
        else:
            shader = RELIEF_SHADER
            if mode==2:
                # Bake the saved full-resolution normal field to diffuse vertex colors.
                # The UV GLB export retains an actual normal texture for external viewers.
                normals = np.load(self.selected/'normals.npy', allow_pickle=False)
                normals = cv2.resize(normals, size); light = np.array([-.4, .5, .76]); light /= np.linalg.norm(light)
                rgba[:, :3] *= (.25+.75*np.maximum(0, normals@light)).reshape(-1, 1)
                vertices[:, 2] = 0; shader = None
            self.preview_item = gl.GLMeshItem(vertexes=vertices, faces=mesh.faces, vertexColors=rgba,
                smooth=True, shader=shader, drawEdges=False, computeNormals=True)
        self.view.addItem(self.preview_item)
        if not hasattr(self, '_view_source') or self._view_source!=self.selected:
            self.fit_view()
            self._view_source = self.selected

    def fit_view(self):
        if self.z is None: return
        width = self.width_mm.value(); height = width*(self.z.shape[0]-1)/(self.z.shape[1]-1)
        radius = np.sqrt(width**2+height**2+(self.relief.value()/10)**2)/2
        aspect = max(1., self.view.width()/max(1, self.view.height()))
        angle = np.arctan(np.tan(np.radians(self.view.opts['fov']/2))/aspect)
        self.view.opts['center'] = QVector3D(0, 0, self.relief.value()/20)
        self.view.setCameraPosition(distance=float(radius/np.sin(angle)*1.1), elevation=55, azimuth=-60)

    def print_surface(self):
        if self.selected is None: return self.error('Select a saved capture or panorama first.')
        source, width, relief, base = self.selected, self.width_mm.value(), self.relief.value()/10, self.base_mm.value()
        self.run_job(lambda progress:export_print(source, width, relief, base, progress),
                     lambda folder:self.status.setText('STL and validation report saved: '+str(folder)))

    def open_output(self):
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.selected or self.project.root)))

    def set_busy(self, busy):
        for widget in self.actions+[self.devices, self.resolutions, self.table, self.assemblies]: widget.setEnabled(not busy)
        self.cancel_button.setEnabled(busy)

    def run_job(self, operation, done):
        if self.job is not None: return
        self.set_busy(True); self.job = Job(operation)
        self.job.progress.connect(self.job_progress); self.job.result.connect(done); self.job.failed.connect(self.error)
        self.job.finished.connect(self.job_finished); self.job.start()

    def job_progress(self, percent, text): self.progress.setValue(percent); self.status.setText(text)

    def job_finished(self):
        self.job.deleteLater(); self.job = None; self.set_busy(False)

    def cancel(self):
        if self.job: self.job.cancelled.set(); self.status.setText('Cancelling at the next safe checkpoint…')
        elif self.calibration_frames is not None:
            self.calibration_frames = None; self.set_busy(False); self.status.setText('Calibration cancelled.')

    def closeEvent(self, event):
        if self.job:
            self.cancel(); self.status.setText('Finishing cancellation; close the window again when idle.'); event.ignore(); return
        self.stop_camera()
        if self.lock: self.lock.unlock()
        event.accept()


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Native GelSight matrix application')
    parser.add_argument('--project', type=Path)
    args = parser.parse_args()
    app = QApplication([]); app.setApplicationName('GelSight Matrix Studio')
    window = Window(args.project); window.show()
    return app.exec()
