# """
# Tools for managing window size and position.
# """

# WIP - here are some quirks that need work:
#
# - 'win snap 200 percent' moves window up a bit when it should stay centered. may be a side-effect related to
# talon resize() API behavior, which will not increase height beyond 1625 for some reason...perhaps related to
# the height of the largest of my 3 screens (which is height 1600).
#
# - here's a weird one: I have vscode maximized on my left hand screen and say 'win size one thousand by one thousand',
# first it resizes, as expected, but then jumps to my primary Screen to the right.

from typing import Optional, Tuple

import queue
import logging
import time
import threading

from talon import ui, Module, Context, actions, imgui, settings, app, ctrl, cron, events

# globals
from .compass_control import CompassControl, Direction, compass_direction, NonDualDirection, non_dual_direction

# # turn debug messages on and off
testing: bool = True

win_compass_control = None
compass_control = None
ctx_stop = None

# talon stuff

mod = Module()

TAG_NAME = 'window_tweak_running'
tag = mod.tag(TAG_NAME, desc="Enable stop command during continuous window move/resize.")

# context used to enable/disable window_tweak_running tag
ctx = Context()

setting_move_frequency = mod.setting(
    "win_move_frequency",
    type=str,
    default="40ms",
    desc="The update frequency used when moving a window continuously",
)
setting_resize_frequency = mod.setting(
    "win_resize_frequency",
    type=str,
    default="40ms",
    desc="The update frequency used when resizing a window continuously",
)
setting_move_rate = mod.setting(
    "win_continuous_move_rate",
    type=float,
    default=4.5,
    desc="The target speed, in cm/sec, for continuous move operations",
)
setting_resize_rate = mod.setting(
    "win_continuous_resize_rate",
    type=float,
    default=4.0,
    desc="The target speed, in cm/sec, for continuous resize operations",
)
mod.setting(
    "win_hide_move_gui",
    type=int,
    default=0,
    desc="When enabled, the 'Move/Resize Window' GUI will not be shown for continuous move operations.",
)
mod.setting(
    "win_hide_resize_gui",
    type=int,
    default=0,
    desc="When enabled, the 'Move/Resize Window' GUI will not be shown for continuous resize operations.",
)
mod.setting(
    "win_set_queue_timeout",
    type=float,
    default=0.2,
    desc="How long to wait (in seconds) for talon to signal completion of window move/resize requests.",
)
mod.setting(
    "win_set_retries",
    type=int,
    default=1,
    desc="How many times to retry a timed out talon window move/resize request.",
)
setting_verbose_warnings = mod.setting(
    "win_verbose_warnings",
    type=bool,
    default=False,
    # window move and resize requests are not guaranteed
    desc="Whether to generate warnings for anomalous events.",
)

@imgui.open(y=0)
def win_stop_gui(gui: imgui.GUI) -> None:
    gui.text(f"Say 'win stop' or click below.")
    gui.line()
    if gui.button("Stop moving/resizing"):
        actions.user.win_stop()

@imgui.open(x=2100, y=40)
# @imgui.open(x=4000,y=244)
def _win_show_gui(gui: imgui.GUI) -> None:
    w = ui.active_window()

    gui.text(f"== Window ==")

    gui.text(f"Id: {w.id}")
    gui.spacer()

    x = w.rect.x
    y = w.rect.y
    width = w.rect.width
    height = w.rect.height

    gui.text(f"Top Left: {x, y}")
    gui.text(f"Top Right: {x + width, y}")
    gui.text(f"Bottom Left: {x, y + height}")
    gui.text(f"Bottom Right: {x + width, y + height}")
    gui.text(f"Center: {round(w.rect.center.x), round(w.rect.center.y)}")
    gui.spacer()

    gui.text(f"Width: {round(width)}")
    gui.text(f"Height: {round(height)}")

    gui.line()

    gui.text(f"== Mouse ==")

    gui.text(f"Position: {ctrl.mouse_pos()}")

    gui.line()

    screen = w.screen
    gui.text(f"== Screen ==")
    gui.spacer()

    #gui.text(f"Name: {screen.name}")
    # gui.text(f"DPI: {screen.dpi}")
    # gui.text(f"DPI_x: {screen.dpi_x}")
    # gui.text(f"DPI_y: {screen.dpi_y}")
    #gui.text(f"Scale: {screen.scale}")
    #gui.spacer()

    x = screen.visible_rect.x
    y = screen.visible_rect.y
    width = screen.visible_rect.width
    height = screen.visible_rect.height

    gui.text(f"__Visible Rectangle__")
    gui.text(f"Top Left: {round(x), round(y)}")
    gui.text(f"Top Right: {round(x + width), round(y)}")
    gui.text(f"Bottom Left: {round(x), round(y + height)}")
    gui.text(f"Bottom Right: {round(x + width), round(y + height)}")
    gui.text(f"Center: {round(screen.visible_rect.center.x), round(screen.visible_rect.center.y)}")
    gui.spacer()

    gui.text(f"Width: {round(width)}")
    gui.text(f"Height: {round(height)}")

    gui.spacer()

    x = screen.rect.x
    y = screen.rect.y
    width = screen.rect.width
    height = screen.rect.height

    gui.text(f"__Physical Rectangle__")
    gui.text(f"Top Left: {round(x), round(y)}")
    gui.text(f"Top Right: {round(x + width), round(y)}")
    gui.text(f"Bottom Left: {round(x), round(y + height)}")
    gui.text(f"Bottom Right: {round(x + width), round(y + height)}")
    gui.text(f"Center: {round(screen.rect.center.x), round(screen.rect.center.y)}")
    gui.spacer()

    gui.text(f"Width: {round(width)}")
    gui.text(f"Height: {round(height)}")

    gui.line()

    gui.text(f"Say 'win hide' to close this window.")

    gui.line()

    if gui.button("Close"):
        _win_show_gui.hide()

class WinCompassControl:
    def __init__(self):
        self.testing = testing
        self.win_move_test_job = None
        self.win_move_test_direction = None
        self.win_move_test_iteration = None
        self.win_move_test_prior_result = None
        self.win_move_test_target_window1 = None
        self.win_move_test_target_window2 = None
        
    @classmethod
    def confirmation_wait(cls, w: ui.Window) -> Tuple[bool, ui.Rect]:
        import ctypes
        import ctypes.wintypes
        import win32con

        user32 = ctypes.windll.user32
        ole32 = ctypes.windll.ole32

        ole32.CoInitialize(0)

        WinEventProcType = ctypes.WINFUNCTYPE(
            None, 
            ctypes.wintypes.HANDLE,
            ctypes.wintypes.DWORD,
            ctypes.wintypes.HWND,
            ctypes.wintypes.LONG,
            ctypes.wintypes.LONG,
            ctypes.wintypes.DWORD,
            ctypes.wintypes.DWORD
        )

        result = False
        def callback(hWinEventHook, event, hwnd, idObject, idChild, dwEventThread, dwmsEventTime):
            length = user32.GetWindowTextLengthA(hwnd)
            print(f'confirmation_wait: {length=}')
            buff = ctypes.create_string_buffer(length + 1)
            print(f'confirmation_wait: HERE 1')
            user32.GetWindowTextA(hwnd, buff, length + 1)
            print(f'confirmation_wait: HERE 2')
            # print(buff.value)
            print(f'confirmation_wait: in callback - {buff.value}')
            # nonlocal result
            # result = True
            # win32gui.PostThreadMessage(threading.get_native_id(), win32con.WM_MOVE, 0, 0)

        WinEventProc = WinEventProcType(callback)

        user32.SetWinEventHook.restype = ctypes.wintypes.HANDLE
        hook = user32.SetWinEventHook(
            # win32con.EVENT_OBJECT_LOCATIONCHANGE,
            # win32con.EVENT_OBJECT_LOCATIONCHANGE,
            # win32con.WM_MOVE,
            # win32con.WM_MOVE,
            win32con.EVENT_MIN,
            win32con.EVENT_MAX,
            0,
            WinEventProc,
            0,
            # w.app.pid,
            0,
            win32con.WINEVENT_OUTOFCONTEXT
        )
        if hook == 0:
            print('confirmation_wait: SetWinEventHook failed')
            return

        # timeout = settings.get('user.win_set_queue_timeout')
        timeout = 1.0
        sleepy_time = timeout / 100
        timeout_ns = timeout * 1E9
        start_time = time.monotonic_ns()
        msg = ctypes.wintypes.MSG()
        while time.monotonic_ns() - start_time < timeout_ns:
            # if user32.GetMessageW(ctypes.byref(msg), 0, 0, 0) != 0:
            # if user32.PeekMessageW(ctypes.byref(msg), 0, 0, 0, win32con.PM_REMOVE) != 0:
            #     user32.TranslateMessageW(msg)
            #     user32.DispatchMessageW(msg)
            if result:
                break
            time.sleep(sleepy_time)
        elapsed_time_ms = (time.monotonic_ns() - start_time) / 1e6
        if testing:
            print(f'confirmation_wait: done ({elapsed_time_ms} ms)')

        user32.UnhookWinEvent(hook)
        ole32.CoUninitialize()

        return result

    @classmethod
    def win_set_rect_win32(cls, w: ui.Window, rect_in: ui.Rect) -> Tuple[bool, ui.Rect]:
        import win32gui
        import win32con

        old_rect: ui.Rect = w.rect
        rect_id: int = w.id

        # calculate offsets
        delta_left = rect_in.x - old_rect.x
        delta_top = rect_in.y - old_rect.y
        delta_right = rect_in.x + rect_in.width - (old_rect.x + old_rect.width)
        delta_bottom = rect_in.y + rect_in.height - (old_rect.y + old_rect.height)
        print(f'_win_set_rect: {delta_left=}, {delta_top=}, {delta_right=}, {delta_bottom=}')

        # fetch window state information
        tup = win32gui.GetWindowPlacement(rect_id)
        (flags, showCmd, minpos, maxpos, normalpos) = tup
        #  GetWindowPlacement - (0, 1, (-1, -1), (-1, -1), (3076, 447, 4047, 1255))
        print(f'_win_set_rect: GetWindowPlacement BEFORE - {tup}')
        
        # set window
        WPF_ASYNCWINDOWPLACEMENT = 0x0004
        flags = WPF_ASYNCWINDOWPLACEMENT
        showCmd = win32con.SWP_NOACTIVATE | win32con.SWP_NOZORDER
        new_rect = normalpos[0] + delta_left, normalpos[1] + delta_top, normalpos[2] + delta_right, normalpos[3] + delta_bottom
        window_placement = flags, showCmd, minpos, maxpos, new_rect
        result = win32gui.SetWindowPlacement(rect_id, window_placement)
        print(f'_win_set_rect: SetWindowPlacement - {result=}')

        result = False
        result_rect = None
        if not WinCompassControl.confirmation_wait(w):
            ## fetch window state information
            # tup = win32gui.GetWindowPlacement(rect_id)
            # result_rect = tup[4]
            # result = new_rect == result_rect
            print(f'_win_set_rect: confirmation wait failed')

        result = w.rect == rect_in
        print(f'_win_set_rect: returning - {result, w.rect=}')
            
        # just return rect_in for now
        return result, w.rect
    
    @classmethod
    def win_set_rect_win32(cls, old_rect: ui.Rect, rect_id: int, rect_in: ui.Rect) -> Tuple[bool, ui.Rect]:
        print('_win_set_rect: trying win32 api...')
 
        # get window ref
        windows = ui.windows()
        for w in windows:
            if w.id == rect_id:
                break
        else:
            if settings.get('user.win_verbose_warnings') != 0:
                logging.warning(f'_win_set_rect: invalid window id "{rect_id}"')
            return False, old_rect

        return WinCompassControl.win_set_rect_win32(w, rect_in)

    @classmethod
    def win_set_rect(cls, old_rect: ui.Rect, rect_id: int, rect_in: ui.Rect) -> Tuple[bool, ui.Rect]:
        """Callback invoked by CompassControl engine for updating the window rect using talon API"""
        start_time = time.time_ns()
        if not rect_in:
            raise ValueError('rect_in is None')

        max_retries = retries = settings.get('user.win_set_retries')
        queue_timeout = settings.get('user.win_set_queue_timeout')

        # rect update code adapted from https://talonvoice.slack.com/archives/C9MHQ4AGP/p1635971780355900
        q = queue.Queue()
        def on_move(event_win: ui.Window) -> None:
            if event_win == w and w.rect != old_rect:
                q.put(1)
                if testing:
                    print(f'_win_set_rect: win position changed')
        #
        def on_resize(event_win: ui.Window) -> None:
            if event_win == w and w.rect != old_rect:
                q.put(1)
                if testing:
                    print(f'_win_set_rect: win size changed')

        # get window ref
        windows = ui.windows()
        for w in windows:
            if w.id == rect_id:
                break
        else:
            if settings.get('user.win_verbose_warnings') != 0:
                logging.warning(f'_win_set_rect: invalid window id "{rect_id}"')
            return False, w.rect

        if testing:
            print(f'_win_set_rect: starting...{old_rect=}, {rect_in=}, {w.rect=}')

        result = False, old_rect

        while retries >= 0:
            event_count = 0
            if (rect_in.x, rect_in.y) != (w.rect.x, w.rect.y):
                # print(f'_win_set_rect: register win_move')
                ui.register('win_move', on_move)
                event_count += 1
            if (rect_in.width, rect_in.height) != (w.rect.width, w.rect.height):
                # print(f'_win_set_rect: register win_resize')
                ui.register('win_resize', on_resize)
                event_count += 1
            if event_count == 0:
                # sometimes the queue get below times out, yet by the time we loop around here
                # for a retry, the set operation has completed successfully. then, the checks above
                # fall through to this block. so, the result we return is based on whether this is
                # our first time through the loop or not.
                success = retries < max_retries

                # no real work to do
                result = success, rect_in

                if testing:
                    print('_win_set_rect: nothing to do, window already matches given rect.')

                break

            # do it to it
            start_time_rect = time.time_ns()
            w.rect = rect_in.copy()
            try:
                # for testing
                #raise queue.Empty()
                #raise Exception('just testing')

                q.get(timeout=queue_timeout)
                if event_count == 2:
                    q.get(timeout=queue_timeout)

            except queue.Empty:
                print('_win_set_rect: timed out waiting for window update.')

                if retries > 0:
                    print('_win_set_rect: retrying after time out...')
                    retries -= 1
                    continue
                else:
                    print('_win_set_rect: no more retries, failed')

                    if False:
                        print('_win_set_rect: trying win32 api...')
                        WinCompassControl.win_set_rect_win32(old_rect, rect_id, rect_in)

                    # no more retries
                    break
            else:
                if testing:
                    print(f'_win_set_rect: before: {old_rect}')
                    print(f'_win_set_rect: requested: {rect_in}')
                    print(f'_win_set_rect: after: {w.rect}')

                position_matches_request = (rect_in.x, rect_in.y) == (w.rect.x, w.rect.y)
                size_matches_request = (rect_in.width, rect_in.height) == (w.rect.width, w.rect.height)
                if not position_matches_request or not size_matches_request:
                    if False and app.platform == 'linux':
                        print('_win_set_rect: linux - timed out waiting for window update.')

                        if retries > 0:
                            print('_win_set_rect: linux - retrying after time out...')
                            retries -= 1
                            continue
                        else:
                            print('_win_set_rect: linux - no more retries, failed')

                            # no more retries
                            break
                    else:
                        # need to pass rect_id and old_rect here so they can be saved for 'win revert' usage
                        raise compass_control.RectUpdateError(rect_id=rect_id, initial=old_rect, requested=rect_in, actual=w.rect)

                else:
                    result = True, w.rect

                    # done with retry loop
                    break
            finally:
                ui.unregister('win_move',   on_move)
                ui.unregister('win_resize', on_resize)

        elapsed_time_ms = (time.time_ns() - start_time) / 1e6
        if testing:
            print(f'_win_set_rect: done ({elapsed_time_ms} ms)')

        return result

    def win_stop(self) -> None:
        """Callback invoked by CompassControl engine after stopping a continuous operation"""
        win_stop_gui.hide()

    # @classmethod
    # def win_move_test1_watcher(cls, event_win: ui.Window) -> None:
    #     print(f'win_move_test1_watcher: window changed - {event_win=}')

    def win_move_test1_start(self, target_title: Optional[str] = None) -> bool:
        "Continuously move test window in a loop, to catch timeout errors"

        if not self.win_move_test_job:
            if not target_title:
                logging.error(f'win_move_test1: target_title not set')
                return False
                
            # get window handle
            windows = ui.windows()
            for w in windows:
                # if w.title == target_title:
                if w.title == 'junk1.txt - Notepad':
                    self.win_move_test_target_window1 = w
                elif w.title == 'junk2.txt - Notepad':
                    self.win_move_test_target_window2 = w

                if self.win_move_test_target_window1 and self.win_move_test_target_window2:
                    break
            else:
                logging.error(f'win_move_test1: failed to find two windows with title "{target_title}"')
                self.win_move_test_stop()
                return False

            # # register watcher
            # ui.register('win_move', WinCompassControl.win_move_test1_watcher)
            # ui.register('win_resize', WinCompassControl.win_move_test1_watcher)

            self.win_move_test_iteration = 0

            self.win_move_test_direction = compass_direction([])
            
            self.win_move_test_job = cron.interval('10000ms', self.win_move_test1_start)
            if self.testing:
                print(f'win_move_test1: starting - {self.win_move_test_job=}')
        else:
            if self.testing:
                print(f'win_move_test1: iterating')

            if self.win_move_test_iteration % 2 == 0:
                # reverse direction
                if self.win_move_test_direction['up']:
                    self.win_move_test_direction['up'] = False
                    self.win_move_test_direction['down'] = True
                else:
                    self.win_move_test_direction['up'] = True
                    self.win_move_test_direction['down'] = False

            result, rect, horizontal_limit_reached, vertical_limit_reached = actions.user.win_move_pixels(10, self.win_move_test_direction, self.win_move_test_target_window1)

            if result != self.win_move_test_prior_result:
                # error state changed
                # events.write('window_tweak', f'win_move_test1: STATE CHANGED - {result=}')
                print(f'win_move_test1: STATE CHANGED - {result=}')
            self.win_move_test_prior_result = result

            if not result:
                alt_result = actions.user.win_move_pixels(10, self.win_move_test_direction, self.win_move_test_target_window2)
                print(f'win_move_test1: alternate window move returned {alt_result=}')
            
            self.win_move_test_iteration += 1

    def win_move_test_stop(self) -> bool:
        if self.win_move_test_job:
            cron.cancel(self.win_move_test_job)
            self.win_move_test_job = None

        # # unregister watcher
        # ui.unregister('win_move', WinCompassControl.win_move_test1_watcher)
        # ui.unregister('win_resize', WinCompassControl.win_move_test1_watcher)

def on_ready():
    """Callback invoked by Talon, where we populate our global objects"""
    global win_compass_control, compass_control, ctx_stop

    # if testing:
    #     print(f"on_ready: {settings.get('user.win_continuous_move_rate')=}")

    win_compass_control= WinCompassControl()

    compass_control_settings = {
        '_continuous_move_frequency_str':   setting_move_frequency,
        '_continuous_resize_frequency_str': setting_resize_frequency,
        '_continuous_move_rate':            setting_move_rate,
        '_continuous_resize_rate':          setting_resize_rate,
        '_verbose_warnings':                setting_verbose_warnings
    }
    compass_control= CompassControl(
        TAG_NAME,
        win_compass_control.win_set_rect,
        win_compass_control.win_stop,
        compass_control_settings,
        testing
    )

    # context containing the stop command, enabled only when a continuous move/resize is running
    ctx_stop = Context()
    ctx_stop.matches = fr"""
    tag: user.{TAG_NAME}
    """
    @ctx_stop.action_class("user")
    class WindowTweakActions:
        """
        # Commands for controlling continuous window move/resize operations
        """
        def win_stop() -> None:
            "Stops current window move/resize operation"
            compass_control.continuous_stop()

app.register("ready", on_ready)

@mod.action_class
class Actions:
    def win_show() -> None:
        "Shows information about current window position and size"
        _win_show_gui.show()

    def win_hide() -> None:
        "Hides the window information window"
        _win_show_gui.hide()

    def win_stop() -> None:
        "Module action declaration for stopping current window move/resize operation"
        compass_control.continuous_stop()

    def win_move(direction: Optional[Direction] = None) -> None:
        "Move window in small increments in the given direction, until stopped"

        if not direction:
            direction = compass_direction(['center'])

        w = ui.active_window()

        compass_control.mover.continuous_init(w.rect, w.id, w.screen.visible_rect, w.screen.dpi_x, w.screen.dpi_y, direction)

        if settings.get('user.win_hide_move_gui') == 0:
            win_stop_gui.show()

    def win_move_absolute(x: float, y: float, region: Optional[Direction] = None) -> None:
        "Move window to given absolute position, centered on the point indicated by the given region"

        w = ui.active_window()

        compass_control.mover.move_absolute(w.rect, w.id, x, y, region)

    def win_move_to_pointer(region: Optional[NonDualDirection] = non_dual_direction(['north', 'west'])):
        "Move window to pointer position, centered on the point indicated by the given region"

        w = ui.active_window()

        compass_control.mover.resize_to_pointer(w.rect, w.id, w.screen.visible_rect, region)

    def win_stretch(direction: Optional[Direction] = None) -> None:
        "Stretch window in small increments until stopped, optionally in the given direction"

        if not direction:
            direction = compass_direction(['center'])

        w = ui.active_window()
        compass_control.sizer.continuous_init(w.rect, w.id, w.screen.visible_rect, 1, w.screen.dpi_x, w.screen.dpi_y, direction)

        if settings.get('user.win_hide_resize_gui') == 0:
            win_stop_gui.show()

    def win_shrink(direction: Optional[Direction] = None) -> None:
        "Shrink window in small increments until stopped, optionally in the given direction"
        w = ui.active_window()

        if not direction:
            direction = compass_direction(['center'])

        compass_control.sizer.continuous_init(w.rect, w.id, w.screen.visible_rect, -1, w.screen.dpi_x, w.screen.dpi_y, direction)

        if settings.get('user.win_hide_resize_gui') == 0:
            win_stop_gui.show()

    def win_resize_absolute(target_width: float, target_height: float, region: Optional[Direction] = None) -> None:
        "Size window to given absolute dimensions, optionally by stretching/shrinking in the direction indicated by the given region"

        if not region:
            region = compass_direction(['center'])

        w = ui.active_window()

        compass_control.sizer.resize_absolute(w.rect, w.id, target_width, target_height, region)

    def win_resize_to_pointer(nd_direction: NonDualDirection) -> None:
        "Stretch or shrink window to pointer position, centered on the point indicated by the given region"

        w = ui.active_window()

        compass_control.sizer.resize_to_pointer(w.rect, w.id, w.screen.visible_rect, nd_direction)

    def win_move_pixels(distance: int, direction: Optional[Direction] = None, w: Optional[ui.Window] = None) -> None:
        "Move window some number of pixels"

        if not direction:
            direction = compass_direction(['center'])

        if not w:
            w = ui.active_window()

        delta_width, delta_height = compass_control.get_component_dimensions(w.rect, w.id, w.screen.visible_rect, distance, direction, 'move')

        return compass_control.mover.move_pixels_relative(w.rect, w.id, w.screen.visible_rect, delta_width, delta_height, direction)

    def win_move_percent(percent: float, direction: Optional[Direction] = None) -> None:
        "Move window some percentage of the current size"

        if not direction:
            direction = compass_direction(['center'])

        w = ui.active_window()

        delta_width, delta_height = compass_control.get_component_dimensions_by_percent(w.rect, w.id, w.screen.visible_rect, percent, direction, 'move')

        return compass_control.mover.move_pixels_relative(w.rect, w.id, w.screen.visible_rect, delta_width, delta_height, direction)

    def win_resize_pixels(distance: int, direction: Optional[Direction] = None) -> None:
        "Change window size by pixels"
        w = ui.active_window()

        if not direction:
            direction = compass_direction(['center'])

        delta_width, delta_height = compass_control.get_component_dimensions(w.rect, w.id, w.screen.visible_rect, distance, direction, 'resize')

        if testing:
            print(f'win_resize_pixels: {delta_width=}, {delta_height=}')

        compass_control.sizer.resize_pixels_relative(w.rect, w.id, w.screen.visible_rect, delta_width, delta_height, direction)

    def win_resize_percent(percent: float, direction: Optional[Direction] = None) -> None:
        "Change window size by a percentage of current size"

        if not direction:
            direction = compass_direction(['center'])

        w = ui.active_window()

        delta_width, delta_height = compass_control.get_component_dimensions_by_percent(w.rect, w.id, w.screen.visible_rect, percent, direction, 'resize')

        if testing:
            print(f'win_resize_percent: {delta_width=}, {delta_height=}')

        compass_control.sizer.resize_pixels_relative(w.rect, w.id, w.screen.visible_rect, delta_width, delta_height, direction)

    def win_snap_percent(percent: int) -> None:
        "Center window and change size to given percentage of parent screen (in each direction)"

        direction = compass_direction(['center'])

        w = ui.active_window()

        compass_control.snap(w.rect, w.id, w.screen.visible_rect, percent, direction)

    def win_revert() -> None:
        "Restore current window's last remembered size and position"

        w = ui.active_window()
        compass_control.revert(w.rect, w.id)
        
    def win_move_test1_start() -> None:
        "Continuously move test window in a loop, to catch timeout errors"
        win_compass_control.win_move_test1_start('Untitled - Notepad')

    def win_move_test1_stop() -> None:
        "Stop move test 1"
        win_compass_control.win_move_test_stop()

    def win_test_bresenham(num: int) -> None:
        "Test modified bresenham algo"

        if num == 1:
            compass_control.mover.test_bresenham()
