import json
import math
import sys
from pathlib import Path

from PyQt5 import QtCore, QtGui, QtWidgets, uic

from PIL import ImageGrab  # type: ignore
import pyautogui  # type: ignore


def resource_path(relative: str) -> str:
    """
    Absolute path to resource file.
    Works for:
    - normal run: python main.py (PyCharm, console)
    - PyInstaller: onefile / onedir exe
    """
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        # Running from PyInstaller bundle
        base = Path(sys._MEIPASS)  # type: ignore[attr-defined]
    else:
        # Running from source
        base = Path(__file__).resolve().parent
    return str(base / relative)


def app_dir() -> Path:
    """
    Directory where the EXE lives (PyInstaller) or where main.py lives (source).
    This is where we want default.json to be read/written.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


# Binds requested: 1-9 and F1-F12
BINDS = [str(i) for i in range(1, 10)] + [f"F{i}" for i in range(1, 13)]

APP_DIR = app_dir()
DEFAULT_PROFILE = APP_DIR / "default.json"


class EnterToPickDialog(QtWidgets.QDialog):
    """Modal dialog: on Enter capture current mouse position."""

    picked = QtCore.pyqtSignal(int, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Pick pixel")
        self.setModal(True)
        self.setFixedSize(340, 130)
        layout = QtWidgets.QVBoxLayout(self)

        lbl = QtWidgets.QLabel("Press Enter on destination", self)
        lbl.setAlignment(QtCore.Qt.AlignCenter)
        font = lbl.font()
        font.setPointSize(11)
        lbl.setFont(font)
        layout.addWidget(lbl)

        hint = QtWidgets.QLabel("(Esc = cancel)", self)
        hint.setAlignment(QtCore.Qt.AlignCenter)
        layout.addWidget(hint)

    def keyPressEvent(self, event: QtGui.QKeyEvent):
        if event.key() in (QtCore.Qt.Key_Return, QtCore.Qt.Key_Enter):
            x, y = pyautogui.position()
            self.picked.emit(int(x), int(y))
            self.accept()
            return
        if event.key() == QtCore.Qt.Key_Escape:
            self.reject()
            return
        super().keyPressEvent(event)


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        uic.loadUi(resource_path("ui_main.ui"), self)

        # Style: make pick buttons look like small ovals
        oval_css = (
            "QPushButton {"
            "border: 2px solid #222;"
            "border-radius: 9px;"
            "background: white;"
            "text-align: center;"
            "color: black;"
            "}"
            "QPushButton:pressed { background: #eaeaea; }"
        )

        # Only styling buttons that exist in the UI now (Vitals side)
        for name in [
            "btnPick_hp_spell", "btnPick_hp_pot", "btnPick_mana_pot", "btnPick_mana_burn"
        ]:
            if hasattr(self, name):
                btn = getattr(self, name)
                btn.setStyleSheet(oval_css)
                btn.setText("")

                # Populate bind combos for ALL fields
        for cmb_name in [
            "cmb_hp_spell", "cmb_hp_pot", "cmb_mana_pot", "cmb_mana_burn",
            "cmb_timed1", "cmb_timed2", "cmb_timed3", "cmb_food"
        ]:
            if hasattr(self, cmb_name):
                cmb = getattr(self, cmb_name)
                cmb.addItem("-")
                cmb.addItems(BINDS)

        # Hook up pick buttons (only for Vitals)
        self.btnPick_hp_spell.clicked.connect(lambda: self.pick_for("hp_spell"))
        self.btnPick_hp_pot.clicked.connect(lambda: self.pick_for("hp_pot"))
        self.btnPick_mana_pot.clicked.connect(lambda: self.pick_for("mana_pot"))

        if hasattr(self, "btnPick_mana_burn"):
            self.btnPick_mana_burn.clicked.connect(lambda: self.pick_for("mana_burn"))

        # Start/Stop
        self.btnStart.clicked.connect(self.start_loop)
        self.btnStop.clicked.connect(self.stop_loop)

        # Save/Load (profiles)
        self.btnSave.clicked.connect(self.save_profile_as)
        self.btnLoad.clicked.connect(self.load_profile_dialog)

        # Main loop timer
        self.loop_timer = QtCore.QTimer(self)
        self.loop_timer.timeout.connect(self.on_tick)

        # Counters for timed spells (in ticks)
        self._timed_ticks_since = {"timed1": 0, "timed2": 0, "timed3": 0, "food": 0}

        self.btnStop.setEnabled(False)

        # Keep last folder for dialogs
        self._last_dir = str(APP_DIR)

        # Static text for Tabs (English)
        if hasattr(self, "txtSpellsCds"):
            self.txtSpellsCds.setPlainText(
                "List typical spell timers (can vary depending on serv):\n\n"
                "- Healing Spell: 1s\n"
                "- Haste (utani hur): 31s\n"
                "- Strong Haste (utani gran hur): 22s\n"
                "- Invisible (utana vid): 200s\n"
                "- Magic Shield (utamo vita): 60s\n"
                "- Skill Increase (utito tempo, utito tempo san, utamo tempo): 10s\n"
                "- Party Buffs: 120s\n"
                "- Recovery (utura / utura gran): 60s\n"
                "- Summon Familiar: MAN YOU DON'T NEED BOT FOR THAT"

            )

        if hasattr(self, "txtHowTo"):
            self.txtHowTo.setPlainText(
                "Usage Instructions:\n"
                "1. Select a Key (Bind) for the action.\n"
                "2. Click 'Pick' and press ENTER on the place where you want to trigger spell/pot on TOP BAR.\n"
                "3. Set the Loop Timer (ms) - for most servers default (1000) is optimal.\n"
                "4. Click START.\n\n"
                "Algorithm:\n"
                "Uses hp spell > if hp is low hp pot if not checks mana - it wont try to use both mana and hp pot same time\n"
                "Spells are in sequence, spell 1 is more important then spell 2 etc\n"
                "Better take some margin on essential spells like 58sec for utamo vita and put it as top priority\n"
                "If 2 spells are about to be used in same time it uses spell 1 and in next loop spell 2\n\n"
                "More info with some screens in GitHub\n\n"
                "Dedicated for win10/11 and win7 with SP1 + UniversalC Runtime"
            )

        # Load default profile from app directory on startup (if present)
        self.load_profile(DEFAULT_PROFILE, silent=True)

        # Safety: move mouse to top-left to abort pyautogui
        pyautogui.FAILSAFE = True

    # ---------- Pixel picker ----------
    def pick_for(self, key: str):
        dlg = EnterToPickDialog(self)
        dlg.picked.connect(lambda x, y: self._apply_pick(key, x, y))
        dlg.exec_()

    def _apply_pick(self, key: str, x: int, y: int):
        getattr(self, f"spnX_{key}").setValue(x)
        getattr(self, f"spnY_{key}").setValue(y)
        self.lblStatus.setText(f"Status: picked ({x}, {y}) for {key}")

    # ---------- Loop control ----------
    def start_loop(self):
        interval = int(self.spnTimerMs.value())
        self.loop_timer.start(max(10, interval))
        self.btnStart.setEnabled(False)
        self.btnStop.setEnabled(True)
        self.lblStatus.setText(f"Status: running ({interval} ms)")

        # reset timed spell counters so first cast happens after the full cooldown
        self._timed_ticks_since = {"timed1": 0, "timed2": 0, "timed3": 0, "food": 0}

    def stop_loop(self):
        self.loop_timer.stop()
        self.btnStart.setEnabled(True)
        self.btnStop.setEnabled(False)
        self.lblStatus.setText("Status: stopped")

    # ---------- Core logic ----------
    def on_tick(self):
        interval_ms = int(self.spnTimerMs.value())

        # increment timed counters
        for k in self._timed_ticks_since:
            self._timed_ticks_since[k] += 1

        # 1) HP spell: at most once per tick
        self._process_hp_spell()

        # 2) Potions: at most one per tick (HP potion priority)
        self._process_pots()

        # 3) Mana Burn
        self._process_mana_burn()

        # 4) Timed spells (Rotation): at most one per tick (priority: 1 > 2 > 3)
        self._process_timed_spells(interval_ms)

        # 5) Food: Independent
        self._process_food(interval_ms)

    def _process_hp_spell(self):
        if not self.chk_hp_spell.isChecked():
            return
        bind = self.cmb_hp_spell.currentText().strip()
        if not bind or bind == "-":
            return
        x = int(self.spnX_hp_spell.value())
        y = int(self.spnY_hp_spell.value())
        try:
            r, g, b = self.read_pixel_rgb(x, y)
            if g < 100:
                self.press_key(bind)
                self.lblStatus.setText(f"Status: HP spell -> {bind} (R={r})")
        except Exception as e:
            self.lblStatus.setText(f"Status: HP spell error -> {e}")

    def _process_pots(self):
        # HP potion has priority over Mana potion

        # Try HP potion
        if self.chk_hp_pot.isChecked():
            bind = self.cmb_hp_pot.currentText().strip()
            if bind and bind != "-":
                x = int(self.spnX_hp_pot.value())
                y = int(self.spnY_hp_pot.value())
                try:
                    r, g, b = self.read_pixel_rgb(x, y)
                    if g < 100:
                        self.press_key(bind)
                        self.lblStatus.setText(f"Status: HP potion -> {bind} (R={r})")
                        return  # Stop checking pots
                except Exception as e:
                    self.lblStatus.setText(f"Status: HP potion error -> {e}")
                    return

        # If HP potion not fired, try Mana potion
        if self.chk_mana_pot.isChecked():
            bind = self.cmb_mana_pot.currentText().strip()
            if not bind or bind == "-":
                return
            x = int(self.spnX_mana_pot.value())
            y = int(self.spnY_mana_pot.value())
            try:
                r, g, b = self.read_pixel_rgb(x, y)
                if b < 100:
                    self.press_key(bind)
                    self.lblStatus.setText(f"Status: Mana potion -> {bind} (B={b})")
            except Exception as e:
                self.lblStatus.setText(f"Status: Mana potion error -> {e}")

    def _process_mana_burn(self):
        if not hasattr(self, "chk_mana_burn") or not self.chk_mana_burn.isChecked():
            return

        bind = self.cmb_mana_burn.currentText().strip()
        if not bind or bind == "-":
            return

        x = int(self.spnX_mana_burn.value())
        y = int(self.spnY_mana_burn.value())

        try:
            r, g, b = self.read_pixel_rgb(x, y)
            # Trigger: Blue > 100
            if b > 100:
                self.press_key(bind)
                self.lblStatus.setText(f"Status: Mana burn -> {bind} (B={b})")
        except Exception as e:
            self.lblStatus.setText(f"Status: Mana burn error -> {e}")

    def _process_timed_spells(self, interval_ms: int):
        priorities = ["timed1", "timed2", "timed3"]
        for key in priorities:
            if not getattr(self, f"chk_{key}").isChecked():
                continue
            bind = getattr(self, f"cmb_{key}").currentText().strip()
            if not bind or bind == "-":
                continue
            cd_sec = int(getattr(self, f"spnCd_{key}").value())

            ticks_needed = max(1, int(math.ceil((cd_sec * 1000.0) / max(10, interval_ms))))
            if self._timed_ticks_since[key] >= ticks_needed:
                self.press_key(bind)
                self._timed_ticks_since[key] = 0
                self.lblStatus.setText(f"Status: {key} -> {bind} (CD={cd_sec}s)")
                return  # only one timed spell from rotation per tick

    def _process_food(self, interval_ms: int):
        if not hasattr(self, "chk_food") or not self.chk_food.isChecked():
            return

        bind = self.cmb_food.currentText().strip()
        if not bind or bind == "-":
            return

        cd_sec = int(self.spnCd_food.value())
        ticks_needed = max(1, int(math.ceil((cd_sec * 1000.0) / max(10, interval_ms))))

        if self._timed_ticks_since["food"] >= ticks_needed:
            self.press_key(bind)
            self._timed_ticks_since["food"] = 0
            self.lblStatus.setText(f"Status: Food -> {bind} (CD={cd_sec}s)")

    # ---------- Helpers ----------
    @staticmethod
    def read_pixel_rgb(x: int, y: int):
        img = ImageGrab.grab(bbox=(x, y, x + 1, y + 1))
        px = img.getpixel((0, 0))
        if isinstance(px, int):
            return px, px, px
        if len(px) >= 3:
            return px[0], px[1], px[2]
        return 0, 0, 0

    @staticmethod
    def press_key(bind: str):
        pyautogui.press(bind.lower())

    # ---------- Profiles: Save/Load ----------
    def collect_state(self):
        rows_vitals = ["hp_spell", "hp_pot", "mana_pot", "mana_burn"]
        rows_timed = ["timed1", "timed2", "timed3", "food"]

        data = {
            "timer_ms": int(self.spnTimerMs.value()),
            "rows": {}
        }

        # Save Vitals (with X/Y)
        for r in rows_vitals:
            if not hasattr(self, f"chk_{r}"): continue
            data["rows"][r] = {
                "enabled": bool(getattr(self, f"chk_{r}").isChecked()),
                "bind": str(getattr(self, f"cmb_{r}").currentText()),
                "x": int(getattr(self, f"spnX_{r}").value()),
                "y": int(getattr(self, f"spnY_{r}").value()),
            }

        # Save Timed (no X/Y, only CD)
        for r in rows_timed:
            if not hasattr(self, f"chk_{r}"): continue
            data["rows"][r] = {
                "enabled": bool(getattr(self, f"chk_{r}").isChecked()),
                "bind": str(getattr(self, f"cmb_{r}").currentText()),
                "cd_sec": int(getattr(self, f"spnCd_{r}").value())
            }

        return data

    def apply_state(self, data: dict):
        self.spnTimerMs.setValue(int(data.get("timer_ms", 1000)))
        rows = data.get("rows", {})

        for r, v in rows.items():
            if not hasattr(self, f"chk_{r}"):
                continue
            getattr(self, f"chk_{r}").setChecked(bool(v.get("enabled", False)))

            bind = v.get("bind", "-")
            cmb = getattr(self, f"cmb_{r}")
            idx = cmb.findText(bind)
            if idx < 0:
                idx = 0
            cmb.setCurrentIndex(idx)

            # Apply X/Y only if they exist in UI (Vitals)
            if hasattr(self, f"spnX_{r}"):
                getattr(self, f"spnX_{r}").setValue(int(v.get("x", 0)))
                getattr(self, f"spnY_{r}").setValue(int(v.get("y", 0)))

            # Apply CD only if exists (Timed)
            if hasattr(self, f"spnCd_{r}"):
                getattr(self, f"spnCd_{r}").setValue(int(v.get("cd_sec", 10)))

    def save_profile_as(self):
        default_name = "default.json"
        start_path = str(Path(self._last_dir) / default_name)
        filename, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Save profile",
            start_path,
            "JSON files (*.json);;All files (*.*)",
        )
        if not filename:
            return
        self._last_dir = str(Path(filename).resolve().parent)

        data = self.collect_state()
        try:
            with open(filename, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            self.lblStatus.setText(f"Status: saved profile -> {Path(filename).name}")
        except Exception as e:
            self.lblStatus.setText(f"Status: save error -> {e}")

    def load_profile_dialog(self):
        start_dir = self._last_dir
        filename, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Load profile",
            start_dir,
            "JSON files (*.json);;All files (*.*)",
        )
        if not filename:
            return
        self._last_dir = str(Path(filename).resolve().parent)
        self.load_profile(Path(filename), silent=False)

    def load_profile(self, path: Path, silent: bool = False):
        try:
            if not path.exists():
                if not silent:
                    self.lblStatus.setText(f"Status: profile not found -> {path.name}")
                return
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.apply_state(data)
            if not silent:
                self.lblStatus.setText(f"Status: loaded profile <- {path.name}")
        except Exception as e:
            if not silent:
                self.lblStatus.setText(f"Status: load error -> {e}")


def main():
    app = QtWidgets.QApplication(sys.argv)
    w = MainWindow()
    w.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()