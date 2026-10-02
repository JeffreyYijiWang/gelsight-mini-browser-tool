"""Native Qt smoke test. Synthetic capture workflow; optional real preview only."""
import argparse
import json
from pathlib import Path
import sys
import time
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import desktop_studio
import numpy as np
from PySide6.QtCore import QObject
from PySide6.QtWidgets import QApplication
from desktop_studio.app import Window

parser = argparse.ArgumentParser()
parser.add_argument('--hardware', action='store_true')
args = parser.parse_args()
app = QApplication([])
folder = ROOT/'test-artifacts'/('native-'+uuid4().hex[:8])
window = Window(folder)
errors = []
window.error = lambda text:errors.append(text)
window.show()


def wait(predicate, timeout=60):
    deadline = time.monotonic()+timeout
    while not predicate():
        app.processEvents()
        if errors: raise AssertionError(errors)
        if time.monotonic()>deadline: raise TimeoutError(window.status.text())
        time.sleep(.01)
    app.processEvents()


if args.hardware:
    window.connect_camera()
    wait(lambda:window.frame_number>=10, 20)
    report = dict(real_camera_frames=window.frame_number, shape=list(window.latest.shape),
                  device=window.device_key(), baseline_captured=False, samples_saved=False)
    window.grab().save(str(folder/'hardware-preview.png'))
    window.stop_camera()
else:
    # Deliver known synthetic frames through the same UI callback. No physical
    # no-contact state is assumed and no real camera is calibrated by this test.
    class FixtureCamera(QObject):
        def stop(self): pass
    window.camera = FixtureCamera(window)
    window.device_key = lambda:'SYNTHETIC native smoke fixture'
    y, x = np.indices((240, 320))
    raw = np.stack((130+20*np.sin(x*.17), 145+20*np.cos(y*.13), 120+20*np.sin((x+y)*.09)), -1).astype(np.uint8)
    window.accept_rgb(raw)
    window.begin_calibration()
    for i in range(50): window.accept_rgb(raw)
    wait(lambda:window.job is None and window.calibration is not None)
    for index in range(3):
        if index==2: window.row_button.click()
        window.accept_rgb(np.roll(raw, 5+index*7, axis=1))
        window.capture_button.click()
        wait(lambda:window.job is None)
    assert list(map(len, window.project.data['rows']))==[2, 1]
    # A new live frame must not replace the selected saved map or its selection.
    window.image_mode.setCurrentText('Normal')
    selected = window.selected
    saved_key = window.image_view.pixmap().cacheKey()
    live_key = window.live_view.pixmap().cacheKey()
    window.tabs.setCurrentWidget(window.live_tab)
    window.accept_rgb(np.roll(raw, 43, axis=0))
    assert window.live_view.pixmap().cacheKey()!=live_key
    assert window.image_view.pixmap().cacheKey()==saved_key
    assert window.selected==selected and window.image_mode.currentText()=='Normal'
    assert window.tabs.currentWidget() is window.live_tab
    window.grab().save(str(folder/'live-tab.png'))
    window.assemble(); wait(lambda:window.job is None, 90)
    assert len(window.project.data['assemblies'])==1
    window.tabs.setCurrentIndex(1); window.relief.setValue(35)
    for mode in range(3):
        window.view_mode.setCurrentIndex(mode); window.render_3d(); app.processEvents()
        wait(lambda:window.preview_item is not None)
    window.view_mode.setCurrentIndex(0); window.render_3d(); app.processEvents()
    window.grab().save(str(folder/'native-window.png'))
    window.print_surface(); wait(lambda:window.job is None, 90)
    reports = list(window.selected.glob('prints/*/validation.json'))
    assert len(reports)==1 and json.loads(reports[0].read_text())['roundtrip_passed']
    report = dict(synthetic=True, rows=[2, 1], surface_shape=list(window.z.shape),
                  print_validation=json.loads(reports[0].read_text()), independent_live_tab=True, errors=errors)
window.stop_camera()
assert window.live_view.text()=='Camera disconnected'
window.close(); app.processEvents()
(folder/'smoke-report.json').write_text(json.dumps(report, indent=2))
print(json.dumps({'folder':str(folder), **report}, indent=2))
