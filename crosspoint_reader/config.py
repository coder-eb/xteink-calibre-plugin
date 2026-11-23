from calibre.utils.config import JSONConfig
from qt.core import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .log import get_log_text


PREFS = JSONConfig('plugins/crosspoint_reader')
PREFS.defaults['host'] = '192.168.4.1'
PREFS.defaults['port'] = 81
PREFS.defaults['path'] = '/'
PREFS.defaults['chunk_size'] = 2048
PREFS.defaults['debug'] = False
PREFS.defaults['fetch_metadata'] = False
PREFS.defaults['send_to_root'] = False
PREFS.defaults['overwrite_existing'] = False
PREFS.defaults['upload_template'] = ''
PREFS.defaults['upload_retries'] = 3
PREFS.defaults['retry_delay'] = 2
PREFS.defaults['book_cooldown'] = 1
PREFS.defaults['socket_timeout'] = 30
# Optimizer settings (mirrors the CrossPoint web server optimizer).
PREFS.defaults['optimize'] = False
PREFS.defaults['optimize_grayscale'] = True
PREFS.defaults['optimize_auto_crop'] = False
PREFS.defaults['optimize_quality'] = 70
PREFS.defaults['optimize_contrast'] = True    # x1.2 around mid-grey
PREFS.defaults['optimize_quantize'] = False   # snap to the panel's 4 grey levels (bigger files on photos)
PREFS.defaults['optimize_cover_color'] = False
PREFS.defaults['optimize_css'] = True         # drop unused CSS rules/stylesheets
PREFS.defaults['optimize_section_kb'] = 0     # 0 = stock CrossPoint; 32 = larger sections
PREFS.defaults['optimize_split'] = True
PREFS.defaults['device_target'] = 'auto'  # 'auto' | 'X4' | 'X3'


class CrossPointConfigWidget(QWidget):
    def __init__(self):
        super().__init__()
        layout = QFormLayout(self)
        layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        self.host = QLineEdit(self)
        self.port = QSpinBox(self)
        self.port.setRange(1, 65535)
        self.path = QLineEdit(self)
        self.upload_template = QLineEdit(self)
        self.chunk_size = QSpinBox(self)
        self.chunk_size.setRange(512, 65536)
        self.upload_retries = QSpinBox(self)
        self.upload_retries.setRange(0, 10)
        self.retry_delay = QSpinBox(self)
        self.retry_delay.setRange(0, 60)
        self.retry_delay.setSuffix(' s')
        self.book_cooldown = QSpinBox(self)
        self.book_cooldown.setRange(0, 60)
        self.book_cooldown.setSuffix(' s')
        self.socket_timeout = QSpinBox(self)
        self.socket_timeout.setRange(5, 300)
        self.socket_timeout.setSuffix(' s')
        self.debug = QCheckBox('Enable debug logging', self)
        self.fetch_metadata = QCheckBox('Fetch metadata for side-loaded books (downloads each once on connect)', self)
        self.send_to_root = QCheckBox('Send to root (ignore any template)', self)
        self.overwrite_existing = QCheckBox('Overwrite file if it already exists on the device', self)

        # Optimizer controls.
        self.optimize = QCheckBox('Optimize EPUBs before transfer', self)
        self.optimize_grayscale = QCheckBox('Convert images to grayscale', self)
        self.optimize_auto_crop = QCheckBox('Auto-crop uniform margins', self)
        self.optimize_split = QCheckBox(
            'Split large chapters/paragraphs, remove fonts (prevents out-of-memory)', self)
        self.optimize_contrast = QCheckBox('Boost image contrast (x1.2)', self)
        self.optimize_quantize = QCheckBox(
            'Snap images to the screen\'s 4 grey levels (smaller files; needs grayscale)', self)
        self.optimize_cover_color = QCheckBox(
            'Keep the cover in colour (the device greys it itself)', self)
        self.optimize_css = QCheckBox('Remove unused CSS (faster chapter loading)', self)
        self.optimize_section_kb = QComboBox(self)
        self.optimize_section_kb.addItem('Stock CrossPoint (about 9 KB, safest)', 0)
        self.optimize_section_kb.addItem('Larger (about 32 KB, fewer files, faster)', 32)
        self.optimize_quality = QSpinBox(self)
        self.optimize_quality.setRange(1, 100)
        self.optimize_quality.setSuffix('%')
        self.device_target = QComboBox(self)
        self.device_target.addItem('Auto-detect', 'auto')
        self.device_target.addItem('X4 (480×800)', 'X4')
        self.device_target.addItem('X3 (528×792)', 'X3')

        self.host.setText(PREFS['host'])
        self.port.setValue(PREFS['port'])
        self.path.setText(PREFS['path'])
        self.upload_template.setText(PREFS['upload_template'])
        self.upload_template.setPlaceholderText("Leave blank to use Calibre's send-to-device template")
        self.chunk_size.setValue(PREFS['chunk_size'])
        self.upload_retries.setValue(PREFS['upload_retries'])
        self.retry_delay.setValue(PREFS['retry_delay'])
        self.book_cooldown.setValue(PREFS['book_cooldown'])
        self.socket_timeout.setValue(PREFS['socket_timeout'])
        self.debug.setChecked(PREFS['debug'])
        self.fetch_metadata.setChecked(PREFS['fetch_metadata'])
        self.send_to_root.setChecked(PREFS['send_to_root'])
        self.overwrite_existing.setChecked(PREFS['overwrite_existing'])
        self.optimize.setChecked(PREFS['optimize'])
        self.optimize_grayscale.setChecked(PREFS['optimize_grayscale'])
        self.optimize_auto_crop.setChecked(PREFS['optimize_auto_crop'])
        self.optimize_split.setChecked(PREFS['optimize_split'])
        self.optimize_quality.setValue(PREFS['optimize_quality'])
        self.optimize_contrast.setChecked(PREFS['optimize_contrast'])
        self.optimize_quantize.setChecked(PREFS['optimize_quantize'])
        self.optimize_cover_color.setChecked(PREFS['optimize_cover_color'])
        self.optimize_css.setChecked(PREFS['optimize_css'])
        sidx = self.optimize_section_kb.findData(PREFS['optimize_section_kb'])
        self.optimize_section_kb.setCurrentIndex(sidx if sidx >= 0 else 0)
        idx = self.device_target.findData(PREFS['device_target'])
        self.device_target.setCurrentIndex(idx if idx >= 0 else 0)

        layout.addRow('Host', self.host)
        layout.addRow('Port', self.port)

        notice = QLabel('Host and port settings are fallback values used only when the device is not auto-discoverable by UDP broadcast.')
        notice.setWordWrap(True)
        notice.setStyleSheet('color: gray; font-style: italic;')
        layout.addRow('', notice)

        layout.addRow('Upload path', self.path)
        layout.addRow('Upload template', self.upload_template)
        layout.addRow('Chunk size', self.chunk_size)

        reliability_heading = QLabel('<b>Upload reliability</b>')
        layout.addRow(reliability_heading)
        reliability_notice = QLabel('Retries resend the current book from the beginning after transient WebSocket failures.')
        reliability_notice.setWordWrap(True)
        reliability_notice.setStyleSheet('color: gray; font-style: italic;')
        layout.addRow('', reliability_notice)
        layout.addRow('Upload retries', self.upload_retries)
        layout.addRow('Retry delay', self.retry_delay)
        layout.addRow('Delay between books', self.book_cooldown)
        layout.addRow('Socket timeout', self.socket_timeout)

        layout.addRow('', self.debug)
        layout.addRow('', self.fetch_metadata)
        layout.addRow('', self.send_to_root)
        layout.addRow('', self.overwrite_existing)

        sep = QFrame(self)
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addRow(sep)

        opt_heading = QLabel('<b>Optimizer</b>')
        layout.addRow(opt_heading)
        opt_notice = QLabel('Resizes images to the screen, converts them to the panel\'s four grey '
                            'levels and re-encodes as JPEG, removes unused CSS, splits chapters '
                            'for the firmware\'s memory limits, then rewrites the EPUB. '
                            'A summary is shown after each transfer.')
        opt_notice.setWordWrap(True)
        opt_notice.setStyleSheet('color: gray; font-style: italic;')
        layout.addRow('', opt_notice)
        layout.addRow('', self.optimize)
        layout.addRow('Device target', self.device_target)
        layout.addRow('JPEG quality', self.optimize_quality)
        layout.addRow('', self.optimize_grayscale)
        layout.addRow('', self.optimize_contrast)
        layout.addRow('', self.optimize_quantize)
        layout.addRow('', self.optimize_cover_color)
        layout.addRow('', self.optimize_auto_crop)
        layout.addRow('', self.optimize_css)
        layout.addRow('', self.optimize_split)
        layout.addRow('Chapter size', self.optimize_section_kb)

        self.optimize.toggled.connect(self._sync_optimizer_enabled)
        self.optimize_grayscale.toggled.connect(lambda _c: self._sync_quantize_enabled())
        self._sync_optimizer_enabled(self.optimize.isChecked())

        self.log_view = QPlainTextEdit(self)
        self.log_view.setReadOnly(True)
        self.log_view.setPlaceholderText('Discovery log will appear here when debug is enabled.')
        self._refresh_logs()

        refresh_btn = QPushButton('Refresh Log', self)
        refresh_btn.clicked.connect(self._refresh_logs)
        log_layout = QHBoxLayout()
        log_layout.addWidget(refresh_btn)

        layout.addRow('Log', self.log_view)
        layout.addRow('', log_layout)

    def save(self):
        PREFS['host'] = self.host.text().strip() or PREFS.defaults['host']
        PREFS['port'] = int(self.port.value())
        PREFS['path'] = self.path.text().strip() or PREFS.defaults['path']
        PREFS['upload_template'] = self.upload_template.text().strip()
        PREFS['chunk_size'] = int(self.chunk_size.value())
        PREFS['upload_retries'] = int(self.upload_retries.value())
        PREFS['retry_delay'] = int(self.retry_delay.value())
        PREFS['book_cooldown'] = int(self.book_cooldown.value())
        PREFS['socket_timeout'] = int(self.socket_timeout.value())
        PREFS['debug'] = bool(self.debug.isChecked())
        PREFS['fetch_metadata'] = bool(self.fetch_metadata.isChecked())
        PREFS['send_to_root'] = bool(self.send_to_root.isChecked())
        PREFS['overwrite_existing'] = bool(self.overwrite_existing.isChecked())
        PREFS['optimize'] = bool(self.optimize.isChecked())
        PREFS['optimize_grayscale'] = bool(self.optimize_grayscale.isChecked())
        PREFS['optimize_auto_crop'] = bool(self.optimize_auto_crop.isChecked())
        PREFS['optimize_split'] = bool(self.optimize_split.isChecked())
        PREFS['optimize_quality'] = int(self.optimize_quality.value())
        PREFS['optimize_contrast'] = bool(self.optimize_contrast.isChecked())
        PREFS['optimize_quantize'] = bool(self.optimize_quantize.isChecked())
        PREFS['optimize_cover_color'] = bool(self.optimize_cover_color.isChecked())
        PREFS['optimize_css'] = bool(self.optimize_css.isChecked())
        PREFS['optimize_section_kb'] = int(self.optimize_section_kb.currentData() or 0)
        PREFS['device_target'] = self.device_target.currentData()

    def _sync_optimizer_enabled(self, enabled):
        for w in (self.optimize_grayscale, self.optimize_auto_crop,
                  self.optimize_split, self.optimize_quality, self.device_target,
                  self.optimize_contrast, self.optimize_quantize,
                  self.optimize_cover_color, self.optimize_css,
                  self.optimize_section_kb):
            w.setEnabled(enabled)
        self._sync_quantize_enabled()

    def _sync_quantize_enabled(self):
        # 4-level snapping is a grayscale operation.
        if self.optimize.isChecked():
            self.optimize_quantize.setEnabled(self.optimize_grayscale.isChecked())

    def _refresh_logs(self):
        self.log_view.setPlainText(get_log_text())

    def validate(self):
        return True


class CrossPointConfigDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('CrossPoint Reader')
        self.widget = CrossPointConfigWidget()
        layout = QVBoxLayout(self)
        layout.addWidget(self.widget)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                                   QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
