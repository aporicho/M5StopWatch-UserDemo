from __future__ import annotations

import subprocess
from typing import Callable

from .platforms import create_platform
from .service import ServiceManager
from .status import StatusSnapshot, collect_status


_controller = None


def _voice_detail(snapshot: StatusSnapshot) -> str:
    if snapshot.ready_for_voice:
        return "Ready"
    missing: list[str] = []
    if not snapshot.service_installed:
        missing.append("service")
    elif not snapshot.service_running:
        missing.append("service running")
    elif not snapshot.runtime.ok:
        missing.append(snapshot.runtime.message)
    if not snapshot.watch_id:
        missing.append("watch")
    if not snapshot.input_permission.ok:
        missing.append("input permission")
    if not snapshot.bluetooth_permission.ok:
        missing.append("Bluetooth permission")
    return "Not ready: " + ", ".join(missing)


def run_app() -> None:
    from AppKit import (  # type: ignore[import-not-found]
        NSApplication,
        NSApplicationActivationPolicyAccessory,
        NSBackingStoreBuffered,
        NSBezelStyleRounded,
        NSButton,
        NSFont,
        NSMakeRect,
        NSMenu,
        NSMenuItem,
        NSStatusBar,
        NSVariableStatusItemLength,
        NSWindow,
        NSWindowStyleMaskClosable,
        NSWindowStyleMaskMiniaturizable,
        NSWindowStyleMaskTitled,
        NSWorkspace,
        NSTextField,
    )
    from Foundation import NSObject  # type: ignore[import-not-found]

    def make_label(text: str, x: float, y: float, width: float, height: float, *, bold: bool = False):
        field = NSTextField.alloc().initWithFrame_(NSMakeRect(x, y, width, height))
        field.setStringValue_(text)
        field.setBezeled_(False)
        field.setDrawsBackground_(False)
        field.setEditable_(False)
        field.setSelectable_(False)
        field.setFont_(NSFont.boldSystemFontOfSize_(13) if bold else NSFont.systemFontOfSize_(13))
        return field

    def make_button(title: str, action: str, x: float, y: float, width: float, target):
        button = NSButton.alloc().initWithFrame_(NSMakeRect(x, y, width, 30))
        button.setTitle_(title)
        button.setBezelStyle_(NSBezelStyleRounded)
        button.setTarget_(target)
        button.setAction_(action)
        return button

    class StatusController(NSObject):
        def init(self):  # noqa: N802
            self = super(StatusController, self).init()
            if self is None:
                return None
            self.status_item = None
            self.window = None
            self.row_values = {}
            self.buttons = {}
            self.menu_items = {}
            self.snapshot = None
            self.last_message = None
            return self

        def setup(self) -> None:
            self._setup_menu()
            self._setup_window()
            self.refresh()

        def _setup_menu(self) -> None:
            self.status_item = NSStatusBar.systemStatusBar().statusItemWithLength_(NSVariableStatusItemLength)
            status_button = self.status_item.button()
            if status_button is not None:
                status_button.setTitle_("M5")
                status_button.setToolTip_("M5StopWatch")

            menu = NSMenu.alloc().init()
            self._add_menu_item(menu, "Open M5StopWatch", "showWindow:")
            self._add_menu_item(menu, "Refresh", "refresh:")
            menu.addItem_(NSMenuItem.separatorItem())
            self.menu_items["install"] = self._add_menu_item(menu, "Install Service", "installService:")
            self.menu_items["start"] = self._add_menu_item(menu, "Start Service", "startService:")
            self.menu_items["stop"] = self._add_menu_item(menu, "Stop Service", "stopService:")
            self.menu_items["restart"] = self._add_menu_item(menu, "Restart Service", "restartService:")
            menu.addItem_(NSMenuItem.separatorItem())
            self._add_menu_item(menu, "Open Accessibility", "openAccessibility:")
            self._add_menu_item(menu, "Open Bluetooth", "openBluetooth:")
            self._add_menu_item(menu, "Open Logs", "openLogs:")
            menu.addItem_(NSMenuItem.separatorItem())
            self._add_menu_item(menu, "Quit", "quit:")
            self.status_item.setMenu_(menu)

        def _add_menu_item(self, menu, title: str, action: str):
            item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, action, "")
            item.setTarget_(self)
            menu.addItem_(item)
            return item

        def _setup_window(self) -> None:
            style = NSWindowStyleMaskTitled | NSWindowStyleMaskClosable | NSWindowStyleMaskMiniaturizable
            self.window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
                NSMakeRect(0, 0, 520, 360),
                style,
                NSBackingStoreBuffered,
                False,
            )
            self.window.setTitle_("M5StopWatch")
            self.window.center()

            content = self.window.contentView()
            content.addSubview_(make_label("M5StopWatch", 24, 316, 220, 24, bold=True))
            self.summary = make_label("Checking...", 24, 292, 460, 20)
            content.addSubview_(self.summary)

            rows = [
                "Service",
                "Watch",
                "Voice",
                "Text Input",
                "Bluetooth",
                "Model",
                "Latest",
            ]
            y = 254
            for row in rows:
                title = make_label(row, 24, y, 110, 18, bold=True)
                value = make_label("", 138, y, 350, 18)
                value.setSelectable_(True)
                content.addSubview_(title)
                content.addSubview_(value)
                self.row_values[row] = value
                y -= 30

            button_specs = [
                ("install", "Install", "installService:", 24, 28, 82),
                ("start", "Start", "startService:", 114, 28, 72),
                ("stop", "Stop", "stopService:", 194, 28, 72),
                ("restart", "Restart", "restartService:", 274, 28, 82),
                ("logs", "Logs", "openLogs:", 364, 28, 60),
                ("refresh", "Refresh", "refresh:", 432, 28, 64),
            ]
            for key, title, action, x, y, width in button_specs:
                button = make_button(title, action, x, y, width, self)
                content.addSubview_(button)
                self.buttons[key] = button

        def applicationShouldTerminateAfterLastWindowClosed_(self, sender):  # noqa: N802
            return False

        def showWindow_(self, sender):  # noqa: N802
            self.refresh()
            self.window.makeKeyAndOrderFront_(sender)
            NSApplication.sharedApplication().activateIgnoringOtherApps_(True)

        def refresh_(self, sender):  # noqa: N802
            self.refresh()

        def refresh(self) -> None:
            self.snapshot = collect_status()
            summary = "Voice ready" if self.snapshot.ready_for_voice else "Voice not ready"
            if self.last_message:
                summary = self.last_message
            self.summary.setStringValue_(summary)

            service_value = "Error: " + self.snapshot.service_error if self.snapshot.service_error else (
                "Running"
                if self.snapshot.service_running
                else ("Stopped" if self.snapshot.service_installed else "Not installed")
            )
            self.row_values["Service"].setStringValue_(service_value)
            self.row_values["Watch"].setStringValue_(
                f"Paired: {self.snapshot.watch_id}" if self.snapshot.watch_id else "Not paired"
            )
            self.row_values["Voice"].setStringValue_(_voice_detail(self.snapshot))
            self.row_values["Text Input"].setStringValue_(self.snapshot.input_permission.message)
            self.row_values["Bluetooth"].setStringValue_(self.snapshot.bluetooth_permission.message)
            self.row_values["Model"].setStringValue_(f"{self.snapshot.engine} / {self.snapshot.model}")
            self.row_values["Latest"].setStringValue_(
                self.last_message or self.snapshot.latest_event or "No log entries yet"
            )

            enabled = {
                "install": not self.snapshot.service_installed,
                "start": self.snapshot.service_installed and not self.snapshot.service_running,
                "stop": self.snapshot.service_running,
                "restart": self.snapshot.service_installed,
            }
            for key, value in enabled.items():
                if key in self.buttons:
                    self.buttons[key].setEnabled_(value)
                if key in self.menu_items:
                    self.menu_items[key].setEnabled_(value)

            status_button = self.status_item.button()
            if status_button is not None:
                status_button.setTitle_("M5 Ready" if self.snapshot.ready_for_voice else "M5")

        def _run_service_action(self, label: str, action: Callable[[ServiceManager], object]) -> None:
            try:
                action(ServiceManager("darwin"))
                self.last_message = f"{label} complete"
            except Exception as exc:
                self.last_message = f"{label} failed: {exc}"
            self.refresh()

        def installService_(self, sender):  # noqa: N802
            self._run_service_action("Install", lambda manager: manager.install([]))

        def startService_(self, sender):  # noqa: N802
            self._run_service_action("Start", lambda manager: manager.start())

        def stopService_(self, sender):  # noqa: N802
            self._run_service_action("Stop", lambda manager: manager.stop())

        def restartService_(self, sender):  # noqa: N802
            self._run_service_action("Restart", lambda manager: manager.restart())

        def openAccessibility_(self, sender):  # noqa: N802
            try:
                create_platform("darwin").open_input_permission_settings()
                self.last_message = "Opened Accessibility settings"
            except Exception as exc:
                self.last_message = f"Open Accessibility failed: {exc}"
            self.refresh()

        def openBluetooth_(self, sender):  # noqa: N802
            try:
                create_platform("darwin").open_bluetooth_permission_settings()
                self.last_message = "Opened Bluetooth settings"
            except Exception as exc:
                self.last_message = f"Open Bluetooth failed: {exc}"
            self.refresh()

        def openLogs_(self, sender):  # noqa: N802
            try:
                snapshot = self.snapshot or collect_status()
                snapshot.log_directory.mkdir(parents=True, exist_ok=True)
                NSWorkspace.sharedWorkspace().openFile_(str(snapshot.log_directory))
                self.last_message = "Opened logs"
            except Exception as exc:
                self.last_message = f"Open logs failed: {exc}"
                subprocess.run(["open", str(collect_status().log_directory)], check=False)
            self.refresh()

        def quit_(self, sender):  # noqa: N802
            NSApplication.sharedApplication().terminate_(sender)

    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)

    global _controller
    _controller = StatusController.alloc().init()
    _controller.setup()
    app.setDelegate_(_controller)
    _controller.showWindow_(None)
    app.run()
