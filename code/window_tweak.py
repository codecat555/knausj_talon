"""
Tools for managing window size and position.

Continuous move/resize machinery adapted from mouse.py.
"""

# WIP - what's up with this error? started putty and tried to move the window...noticed then that the window
# WIP - was not actually focused anymore for some reason and the move worked after clicking on the window.
# WIP - oh, I started putty just after testing the 'draft all' command followed by 'draft submit' (to slack),
# WIP - maybe that had something to do with it also...?
# WIP - Oddly, the line numbers shown below are not accurate...for instance, the code shown for line 1174
# WIP - is actually at line 1213.
#
# 2021-11-27 09:32:48    IO 'win move north'
# 2021-11-27 09:32:48    IO [audio]=1650.000ms [compile]=465.150ms [emit]=53.720ms [decode]=1.138ms [total]=520.008ms
# 2021-11-27 09:32:48    IO self.compass_control.get_continuous_parameters: rate_cps=4.5
# 2021-11-27 09:32:48    IO self.compass_control.get_continuous_parameters: dpms_x=0.192, dpms_y=0.19058823529411761
# 2021-11-27 09:32:48    IO self.compass_control.get_continuous_parameters: returning width_increment=0, height_increment=4.76470588235294
# 2021-11-27 09:32:48    IO self._win_move_continuous: compass_control.continuous_move_width_increment=0, compass_control.continuous_move_height_increment=4.76470588235294
# 2021-11-27 09:32:48    IO win_move_continuous_helper: starting w.rect=Rect(1340, 952, 110, 28)
# 2021-11-27 09:32:48    IO self._win_move_pixels_relative: delta_x=0, delta_y=4.76470588235294, x=1340, y=952
# 2021-11-27 09:32:48    IO self.compass_control._win_set_rect: starting...
# 2021-11-27 09:32:48 ERROR cron interval error <function self._win_move_continuous_helper at 0x00000000ECD19550>
#    13:                           threading.py:930 * # cron thread
#    12:                           threading.py:973 *
#    11:                           threading.py:910 *
#    10:                          talon\cron.py:155 |
#     9:                          talon\cron.py:103 |
#     8:                talon\scripting\rctx.py:233 | # 'cron' user.knausj_talon.code.window_tweak:call()
#     7:                          talon\cron.py:178 | # [stack splice]
#     6: user\knausj_talon\code\window_tweak.py:280 | self._move_it(w, compass_control.continuous_move_width_incr..
#     5: user\knausj_talon\code\window_tweak.py:248 | result, horizontal_limit_reached, vert..
#     4: user\knausj_talon\code\window_tweak.py:826 | result = self.compass_control._win_set_rect(w, ui.Rect(roun..
#     3: user\knausj_talon\code\window_tweak.py:1174| w.rect = rect_in
#     2:                    talon\windows\ui.py:290 |
#     1:                    talon\windows\ui.py:260 |
# pywintypes.error: (1400, 'GetWindowPlacement', 'Invalid window handle.')

# WIP - double check all nonspecific commands use clipping and others do not
# WIP - x_steps should be int, and others
# WIP - assign types to all variables
# WIP - review self.compass_control._win_set_rect() return value handling it cross all instances

# WIP - occasionally continuous operations just stop in the middle somewhere, related to talon move/resize api..._win_set_rect() returns False.

# WIP - 'win snap 200 percent' moves win now up a bit, turns out talon resize() API will not increase
# WIP - height beyond 1625 for some reason...perhaps because the largest of my 3 screens is height 1600?

from typing import Dict, List, Tuple, Optional

import math
import queue
import logging
import sys
import threading
import time

from talon import ui, Module, Context, actions, speech_system, ctrl, imgui, cron, settings, app, registry
from talon.types.point import Point2d
from talon.debug import log_exception

# a type for representing compass directions
Direction = Dict[str, bool]

# turn debug messages on and off
testing: bool = True

class CompassControl:
    def __init__(self):
        # remember the last window for use by the 'win revert' command
        self.last_window: Dict = dict()

        self.continuous_direction = None
        self.continuous_old_rect = None
        self.continuous_mutex = threading.RLock()

        # tag used to enable/disable commands used during window move/resize operations
        self.continuous_tag_name = 'window_tweak_running'
        self.continuous_tag_name_qualified = 'user.' + self.continuous_tag_name

        self.mover = CompassControl.Mover(self)
        self.sizer = CompassControl.Sizer(self)
        
    class Mover:
        def __init__(self, compass_control):
            self.compass_control = compass_control

            self.continuous_move_width_increment = 0
            self.continuous_move_height_increment = 0
            self.continuous_move_job = None
            self.use_line_slope = False
            self.continuous_initial_x = None
            self.continuous_initial_y = None
            self.continuous_final_x = None
            self.continuous_final_y = None

            self.use_bresenham = False
            self.use_walking_bresenham = True
            self.continuous_bres = None

        def _reset_continuous_flags(self) -> None:
            with self.compass_control.continuous_mutex:
                self.continuous_move_width_increment = 0
                self.continuous_move_height_increment = 0
                self.continuous_move_job = None
                
                if self.use_bresenham or self.use_walking_bresenham:
                    self.continuous_bres = None
                elif self.use_line_slope:
                    self.continuous_initial_x = None
                    self.continuous_initial_y = None
                    self.continuous_final_x = None
                    self.continuous_final_y = None

        def _win_move_continuous_helper(self) -> None:

            def _move_it(w: ui.Window, delta_x: float, delta_y: float, direction: Direction) -> Tuple[bool, bool, bool]:
                result, horizontal_limit_reached, vertical_limit_reached = self._win_move_pixels_relative(w, delta_x, delta_y, self.compass_control.continuous_direction)
                if not result or (horizontal_limit_reached and vertical_limit_reached):
                    if testing:
                        print(f'_win_move_continuous_helper: window move is complete. {result=}, {horizontal_limit_reached=}, {vertical_limit_reached=}')
                    self.compass_control._win_stop()
                    return False
                else:
                    if horizontal_limit_reached:
                        self.continuous_move_width_increment = 0

                    if vertical_limit_reached:
                        self.continuous_move_height_increment = 0

                return True

            start_mutex_wait = time.time_ns()

            with self.compass_control.continuous_mutex:
                elapsed_time_ms = (time.time_ns() - start_mutex_wait) / 1e6
                if testing:
                    print(f'win_move_continuous_helper: mutex wait ({elapsed_time_ms} ms)')
                start_time = time.time_ns()

                # if testing:
                #     print(f'win_move_continuous_helper: current thread = {threading.get_native_id()}')

                if not self.continuous_move_job:
                    # seems sometimes this gets called while the job is being canceled, so just return in that case
                    return

                # this can happen if a stop operation is in process when cron calls this method. in that case,
                # we can just return.
                if not self.compass_control.continuous_direction:
                    if self.continuous_resize_job:
                        if settings.get('user.win_verbose_warnings') != 0:
                            # I don't ever expect to see this, that's why it's here
                            logging.warning('win_move_continuous_helper: found null self.compass_control.continuous_direction while a move job is running...')
                    # hakuna matata
                    return

                w = ui.active_window()

                if testing:
                    print(f'win_move_continuous_helper: starting {w.rect=}')

                if round(self.continuous_move_width_increment) or round(self.continuous_move_height_increment):
                    direction_count = sum(self.compass_control.continuous_direction.values())
                    if direction_count != 4:
                        _move_it(w, self.continuous_move_width_increment, self.continuous_move_height_increment, self.compass_control.continuous_direction)
                    else:    # move to center (special case)
                        if self.use_walking_bresenham:
                            initial_x = w.rect.x
                            initial_y = w.rect.y
                            win_move_target_width = self.continuous_move_width_increment
                            win_move_target_height = self.continuous_move_height_increment
                            cumulative_delta_x = cumulative_delta_y = 0
                            center_x = center_y = 0
                            while win_move_target_width != 0 and win_move_target_height != 0:
                                try:
                                    center_x, center_y = next(self.continuous_bres)
                                    # translate center coordinates to top left
                                    x, y = self._translate_top_left_by_region_for_move(w, center_x, center_y, self.compass_control.continuous_direction)
                                    x = round(x)
                                    y = round(y)
                                    if testing:
                                            print(f'win_move_continuous_helper: next bresenham point = {center_x, center_y}, corresponding to top left = {x, y}')
                                            print(f'win_move_continuous_helper: current window top left = {w.rect.x, w.rect.y}')
                                    while (x, y) == (round(w.rect.x), round(w.rect.y)):
                                        center_x, center_y = next(self.continuous_bres)
                                        # translate center coordinates to top left
                                        x, y = self._translate_top_left_by_region_for_move(w, center_x, center_y, self.compass_control.continuous_direction)
                                        x = round(x)
                                        y = round(y)
                                        if testing:
                                            print(f'win_move_continuous_helper: skipped to next bresenham point = {center_x, center_y}, corresponding to top left = {x, y}')
                                except StopIteration:
                                    elapsed_time_ms = (time.time_ns() - start_time) / 1e6
                                    if testing:
                                        print(f'win_move_continuous_helper: StopIteration ({elapsed_time_ms} ms)')

                                    self.compass_control._win_stop()
                                    
                                    return

                                delta_x = abs(x - w.rect.x)
                                if self.continuous_move_width_increment < 0:
                                    delta_x *= -1

                                delta_y = abs(y - w.rect.y)
                                if self.continuous_move_height_increment < 0:
                                    delta_y *= -1

                                if testing:
                                    print(f'win_move_continuous_helper: stepping from {w.rect.x, w.rect.y} to {x, y}, {delta_x=}, {delta_y=}')

                                if not _move_it(w, delta_x, delta_y, self.compass_control.continuous_direction):
                                    elapsed_time_ms = (time.time_ns() - start_time) / 1e6
                                    if testing:
                                        print(f'win_move_continuous_helper: stopped at {w.rect=} ({elapsed_time_ms} ms)')
                                    return

                                cumulative_delta_x = abs(w.rect.x - initial_x)
                                if testing:
                                    print(f'win_move_continuous_helper: {cumulative_delta_x=}, {win_move_target_width=}')
                                if win_move_target_width != 0 and cumulative_delta_x >= abs(win_move_target_width):
                                    if testing:
                                        print(f'win_move_continuous_helper: reached horizontal limit, stopping')
                                    win_move_target_width = 0
                                    break

                                cumulative_delta_y = abs(w.rect.y - initial_y)
                                if testing:
                                    print(f'win_move_continuous_helper: {cumulative_delta_y=}, {win_move_target_height=}')
                                if win_move_target_height != 0 and cumulative_delta_y >= abs(win_move_target_height):
                                    if testing:
                                        print(f'win_move_continuous_helper: reached vertical limit, stopping')
                                    win_move_target_height = 0
                                    break
                else:
                    # move increments are both zero, nothing to do...so stop
                    if testing:
                        print(f'_win_move_continuous_helper: width and height increments are both zero, nothing to do, {w.rect=}')
                    self.compass_control._win_stop()

            elapsed_time_ms = (time.time_ns() - start_time) / 1e6
            if testing:
                print(f'_win_move_continuous_helper: iteration done ({elapsed_time_ms} ms)')
            frequency = float((settings.get('user.win_move_frequency'))[:-2])
            if elapsed_time_ms > frequency:
                if settings.get('user.win_verbose_warnings') != 0:
                    logging.warning(f'_win_move_continuous_helper: iteration took {elapsed_time_ms}ms, longer than the current win_move_frequency setting. actual rate may not match the win_continuous_move_rate setting.')
            
            return

        def _start_move(self) -> None:
            with self.compass_control.continuous_mutex:
                # WIP - for some reason, below doesn't work
                # ctx.tags.add(self.compass_control.continuous_tag_name_qualified)
                ctx.tags = [self.compass_control.continuous_tag_name_qualified]
                self.continuous_move_job = cron.interval(settings.get('user.win_move_frequency'), self._win_move_continuous_helper)
                if testing:
                    print(f'_start_move: {self.continuous_move_job=}')

        def _win_move_continuous(self, w: ui.Window, direction: Direction) -> None:
            with self.compass_control.continuous_mutex:
                if self.continuous_move_job:
                    if testing:
                        print(f'_win_move_continuous: {self.continuous_move_job=}')
                    logging.warning('cannot start a move job when one is already running')
                    return

                self.compass_control._reset_continuous_flags()

                self.compass_control.continuous_direction = direction

                self.compass_control.continuous_old_rect = w.rect

                frequency = float((settings.get('user.win_move_frequency'))[:-2])
                rate = settings.get('user.win_continuous_move_rate')
                self.continuous_move_width_increment, self.continuous_move_height_increment = self.compass_control._get_continuous_parameters(w, rate, direction, 'move', frequency)

                if testing:
                    print(f'_win_move_continuous: {self.continuous_move_width_increment=}, {self.continuous_move_height_increment=}')

                direction_count = sum(self.compass_control.continuous_direction.values())
                if direction_count == 4:    # move to center (special case)
                    # follow path from window center to screen center
                    x0 = round(w.rect.center.x)
                    y0 = round(w.rect.center.y)

                    x1, y1 = self.compass_control._get_target_point(w, direction)

                    x = x_prev = x0
                    y = y_prev = y0

                    if self.use_bresenham or self.use_walking_bresenham:
                        # note that this is based on the line from window center to screen center, resulting coordinates
                        # we'll have to be translated to top left to set window position, etc.
                        self.continuous_bres = self.compass_control.bresenham(x0, y0, x1, y1)

                        # discard initial point (we're already there)
                        first = next(self.continuous_bres)

                self._start_move()

                if settings.get('user.win_hide_move_gui') == 0:
                    _win_stop_gui.show()

        def _clip_to_screen_for_move(self, w, x: float, y: float, width: float, height: float, direction: Direction) -> Tuple[int, int, bool, bool]:
            screen = w.screen
            screen_x = screen.visible_rect.x
            screen_y = screen.visible_rect.y
            screen_width = screen.visible_rect.width
            screen_height = screen.visible_rect.height

            horizontal_limit_reached = vertical_limit_reached = False

            new_x = x
            new_y = y
            if x <= screen_x and direction["left"]:
                new_x = screen_x
                horizontal_limit_reached = True
            elif x >= screen_x + screen_width - width and direction["right"]:
                new_x = screen_x + screen_width - width
                horizontal_limit_reached = True

            if y <= screen_y and direction["up"]:
                new_y = screen_y
                vertical_limit_reached = True
            elif y >= screen_y + screen_height - height and direction["down"]:
                new_y = screen_y + screen_height - height
                vertical_limit_reached = True

            return new_x, new_y, horizontal_limit_reached, vertical_limit_reached

        def _win_move_pixels_relative(self, w: ui.Window, delta_x: float, delta_y: float, direction: Direction) -> Tuple[bool, bool, bool]:
            start_time = time.time_ns()

            result = horizontal_limit_reached = vertical_limit_reached = False

            # start with the current values
            x = w.rect.x
            y = w.rect.y

            if testing:
                print(f'_win_move_pixels_relative: {delta_x=}, {delta_y=}, {x=}, {y=}')

            # apply changes as indicated
            direction_count = sum(direction.values())
            if direction_count == 4:    # move to center
                window_width = w.rect.width
                window_height = w.rect.height

                new_x = x + delta_x
                new_y = y + delta_y

                new_window_center = Point2d(round(new_x + window_width/2), round(new_y + window_height/2))

                window_center = w.rect.center

                screen = w.screen
                screen_center = screen.visible_rect.center

                target_x = screen_center.x - window_width/2
                target_y = screen_center.y - window_height/2

                # calculate distance between window center and screen center
                distance_x = screen_center.x - window_center.x
                distance_y = screen_center.y - window_center.y

                if testing:
                    print(f'_win_move_pixels_relative: {new_x=}, {new_y=}, {screen_center.x=}, {screen_center.y=}')
                    print(f'_win_move_pixels_relative: top left - {target_x=}, {target_y=}')

                if (delta_x != 0):
                    if testing:
                        print(f'_win_move_pixels_relative: {distance_x=}, {delta_x=}')

                    if (delta_x < 0 and (distance_x >= delta_x)) or (delta_x > 0 and (distance_x <= delta_x)):
                        # crossed center point, done moving horizontally
                        if testing:
                            print(f'_win_move_pixels_relative: crossed horizontal center point')
                        new_x = target_x
                        horizontal_limit_reached = True

                if delta_y != 0:
                    if testing:
                        print(f'_win_move_pixels_relative: {distance_y=}, {delta_y=}')

                    if (delta_y < 0 and (distance_y >= delta_y)) or (delta_y > 0 and (distance_y <= delta_y)):
                        # crossed center point, done moving vertically
                        if testing:
                            print(f'_win_move_pixels_relative: crossed vertical center point')
                        new_y = target_y
                        vertical_limit_reached = True
            else:
                if direction["left"]:
                    x -= delta_x

                if direction["right"]:
                    x += delta_x
                #
                if direction["up"]:
                    y -= delta_y

                if direction["down"]:
                    y += delta_y

                new_x, new_y, horizontal_limit_reached, vertical_limit_reached = self._clip_to_screen_for_move(w, x, y, w.rect.width, w.rect.height, direction)

            # make it so
            result = self.compass_control._win_set_rect(w, ui.Rect(round(new_x), round(new_y), round(w.rect.width), round(w.rect.height)))

            if testing:
                if not self.compass_control.last_window:
                    print(f'_win_move_pixels_relative: self.last_window is empty after self.compass_control._win_set_rect(), which returned {result=}')
                elif 'rect' in self.compass_control.last_window:
                    old_rect = self.compass_control.last_window["rect"]
                    delta_x = w.rect.x - old_rect.x
                    delta_y = w.rect.y - old_rect.y
                    delta_width = w.rect.width - old_rect.width
                    delta_height = w.rect.height - old_rect.height
                    # print(f'_win_move_pixels_relative: change: {delta_x=}, {delta_y=}, {delta_width=}, {delta_height=}')

            elapsed_time_ms = (time.time_ns() - start_time) / 1e6
            if testing:
                print(f'_win_move_pixels_relative: done ({elapsed_time_ms} ms)')

            return result, horizontal_limit_reached, vertical_limit_reached

        # note: this method is used by win_move_absolute(), which interprets the Direction
        # argument differently than elsewhere in this module.
        def _translate_top_left_by_region_for_move(self, w: ui.Window, target_x: float, target_y: float, region_in: Direction) -> Tuple[int, int]:

            width = w.rect.width
            height = w.rect.height

            if testing:
                print(f"_translate_top_left_by_region_for_move: initial rect: {w.rect}")
                print(f"_translate_top_left_by_region_for_move: move coordinates: {target_x=}, {target_y=}")

            top_left_x = target_x
            top_left_y = target_y

            direction_count = sum(region_in.values())
            if direction_count == 1:
                if region_in["left"]:
                    top_left_y = target_y - height / 2

                elif region_in["right"]:
                    top_left_x = target_x - width
                    top_left_y = target_y - height / 2

                elif region_in["up"]:
                    top_left_x = target_x - width / 2

                elif region_in["down"]:
                    top_left_x = target_x - width / 2
                    top_left_y = target_y - height

            elif direction_count == 2:
                if region_in["left"] and region_in["up"]:
                    # nothing to do here x and y are already set correctly for this case
                    pass

                elif region_in["right"] and region_in["up"]:
                    top_left_x = target_x - width

                elif region_in["right"] and region_in["down"]:
                    top_left_x = target_x - width
                    top_left_y = target_y - height

                elif region_in["left"] and region_in["down"]:
                    top_left_y = target_y - height

            elif direction_count == 4:
                top_left_x = target_x - width / 2
                top_left_y = target_y - height / 2

            if testing:
                print(f"_translate_top_left_by_region_for_move: translated position: {top_left_x=}, {top_left_y=}")

            return top_left_x, top_left_y

        def _win_test_bresenham_1(self):
            x0 = 0
            y0 = 0
            x1 = 100
            y1 = 4
            max_width = 4
            max_height = 4

            bres = compass_control.bresenham(x0, y0, x1, y1)
            try:
                while True:
                    b0 = next(bres)
                    print(f'_win_test_bresenham_1: bresenham: {b0}')
            except StopIteration:
                print(f'_win_test_bresenham_1: bresenham done')

    class Sizer:
        def __init__(self, compass_control):
            self.compass_control = compass_control
            
            self.continuous_resize_width_increment = 0
            self.continuous_resize_height_increment = 0
            self.continuous_resize_job = None
            self.continuous_resize_alternation = None

        def _reset_continuous_flags(self) -> None:
            with self.compass_control.continuous_mutex:
                self.continuous_resize_width_increment = 0
                self.continuous_resize_height_increment = 0
                self.continuous_resize_job = None

        def _win_resize_continuous_helper(self) -> None:
            start_mutex_wait = time.time_ns()

            with self.compass_control.continuous_mutex:
                elapsed_time_ms = (time.time_ns() - start_mutex_wait) / 1e6
                if testing:
                    print(f'win_resize_continuous_helper: mutex wait ({elapsed_time_ms} ms)')

                start_time = time.time_ns()
                
                if not self.continuous_resize_job:
                    # seems sometimes this gets called while the job is being canceled, so just return that case
                    return

                # this can happen if a stop operation is in process when cron calls this method. in that case,
                # we can just return.
                if not self.compass_control.continuous_direction:
                    if self.continuous_resize_job:
                        if settings.get('user.win_verbose_warnings') != 0:
                            # I don't ever expect to see this, that's why it's here
                            logging.warning('_win_resize_continuous_helper: found null self.compass_control.continuous_direction while a resize job is running...')
                    # hakuna matata
                    return

                if round(self.continuous_resize_width_increment) or round(self.continuous_resize_height_increment):
                    w = ui.active_window()
                    result, resize_left_limit_reached, resize_up_limit_reached, resize_right_limit_reached, resize_down_limit_reached = self._win_resize_pixels_relative(w, self.continuous_resize_width_increment, self.continuous_resize_height_increment, self.compass_control.continuous_direction)

                    # check limits
                    direction_count = sum(self.compass_control.continuous_direction.values())
                    if direction_count == 1:    # horizontal or vertical
                        if any([resize_left_limit_reached, resize_up_limit_reached, resize_right_limit_reached, resize_down_limit_reached]):
                            if testing:
                                print(f'_win_resize_continuous_helper: single direction limit reached')
                            self.continuous_resize_width_increment = 0
                            self.continuous_resize_height_increment = 0
                    elif direction_count == 2:    # diagonal
                        if resize_left_limit_reached or resize_right_limit_reached:
                            if testing:
                                print(f'_win_resize_continuous_helper: horizontal limit reached')
                            self.continuous_resize_width_increment = 0
                        #
                        if resize_up_limit_reached or resize_down_limit_reached:
                            if testing:
                                print(f'_win_resize_continuous_helper: vertical limit reached')
                            self.continuous_resize_height_increment = 0
                    elif direction_count == 4:    # from center
                        if resize_left_limit_reached and resize_right_limit_reached:
                            if testing:
                                print(f'_win_resize_continuous_helper: horizontal limit reached')
                            self.continuous_resize_width_increment = 0

                        if resize_up_limit_reached and resize_down_limit_reached:
                            if testing:
                                print(f'_win_resize_continuous_helper: vertical limit reached')
                            self.continuous_resize_height_increment = 0
                else:
                    # resize increments are both zero, nothing to do...so stop
                    if testing:
                        print('_win_resize_continuous_helper: window resize is complete')
                    self.compass_control._win_stop()

                # for testing
                one_loop_only = False
                if one_loop_only:
                    self.compass_control._win_stop()

            elapsed_time_ms = (time.time_ns() - start_time) / 1e6
            if testing:
                print(f'_win_resize_continuous_helper: iteration done ({elapsed_time_ms} ms)')
            frequency = float((settings.get('user.win_resize_frequency'))[:-2])
            if elapsed_time_ms > frequency:
                if settings.get('user.win_verbose_warnings') != 0:
                    logging.warning(f'_win_resize_continuous_helper: iteration took {elapsed_time_ms}ms, longer than the current win_resize_frequency setting. actual rate may not match the win_continuous_resize_rate setting.')

        def _start_resize(self) -> None:
            with self.compass_control.continuous_mutex:
                # ctx.tags.add(self.compass_control.continuous_tag_name_qualified)
                ctx.tags = [self.compass_control.continuous_tag_name_qualified]
                self.continuous_resize_job = cron.interval(settings.get('user.win_resize_frequency'), self._win_resize_continuous_helper)

        def _win_resize_continuous(self, w: ui.Window, multiplier: int, direction: Optional[Direction] = None) -> None:
            with self.compass_control.continuous_mutex:
                if self.continuous_resize_job:
                    logging.warning('cannot start a resize job when one is already running')
                    return

                frequency = float((settings.get('user.win_resize_frequency'))[:-2])
                rate = settings.get('user.win_continuous_resize_rate')
                self.continuous_resize_width_increment, self.continuous_resize_height_increment = self.compass_control._get_continuous_parameters(w, rate, direction, '_resize', frequency)

                # apply multiplier to control whether we're stretching or shrinking
                self.continuous_resize_width_increment *= multiplier
                self.continuous_resize_height_increment *= multiplier

                self.compass_control.continuous_direction = direction

                self.compass_control.continuous_old_rect = w.rect

                if testing:
                    print(f'_win_resize_continuous: starting resize - {self.continuous_resize_width_increment=}, {self.continuous_resize_height_increment=}, {self.compass_control.continuous_direction=}, {multiplier=}')

                self._start_resize()

                if settings.get('user.win_hide_resize_gui') == 0:
                    _win_stop_gui.show()

        def _translate_top_left_by_region_for_resize(self, w: ui.Window, target_width: float, target_height: float, direction: Direction) -> Tuple[int, int]:

            x = w.rect.x
            y = w.rect.y

            delta_width = target_width - w.rect.width
            delta_height = target_height - w.rect.height

            if settings.get('user.win_verbose_warnings') != 0:
                if abs(delta_width) < 2:
                    logging.warning(f'_translate_top_left_by_region_for_resize: width change is less than 2, which is too small for normal resize calculations: {delta_width=}')
                if abs(delta_height) < 2:
                    logging.warning(f'_translate_top_left_by_region_for_resize: height change is less than 2, which is too small for normal resize calculations: {delta_height=}')

            if testing:
                print(f"_translate_top_left_by_region_for_resize: initial rect: {w.rect}")
                print(f"_translate_top_left_by_region_for_resize: resize coordinates: {target_width=}, {target_height=}")

            direction_count = sum(direction.values())
            if direction_count == 1:
                if direction["left"]:
                    # stretching west, x coordinate must not change for the eastern corners, so push top left to the west
                    x = x - delta_width

                    # adjust y to account for half the change in height
                    y = y - delta_height / 2

                elif direction["up"]:
                    # stretching north, y coordinate must not change for the southern corners,
                    # adjust x to account for half the change in width
                    x = x - delta_width / 2

                    # adjust y to account for the entire change in height
                    y = y - delta_height

                elif direction["right"]:
                    # we are stretching east, so the x coordinate must not change for the western corners, i.e. top left

                    # adjust y to account for half the change in height
                    y = y - delta_height / 2

                elif direction["down"]:
                    # stretching south, y coordinate must not change for the northern corners, i.e. top left

                    # adjust x to account for half the change in width
                    x = x - delta_width / 2

            elif direction_count == 2:
                if direction["left"] and direction["up"]:
                    # we are stretching northwest so the coordinates must not change for the southeastern corner
                    x = x - delta_width
                    y = y - delta_height

                elif direction["right"] and direction["up"]:
                    # we are stretching northeast so the coordinates must not change for the southwestern corner,
                    # adjust y to account for the entire change in height
                    y = y - delta_height

                elif direction["right"] and direction["down"]:
                    # we are stretching southeast so the coordinates must not change for the northwestern corner,
                    # nothing to do here x and y are already set correctly for this case
                    pass

                elif direction["left"] and direction["down"]:
                    # we are stretching southwest so the coordinates must not change for the northeastern corner,
                    # adjust x to account for the entire change in width
                    x = x - delta_width

            elif direction_count == 4:
                x = x - delta_width / 2
                y = y - delta_height / 2

            if testing:
                print(f"_translate_top_left_by_region_for_resize: translated position: {x=}, {y=}, {target_width=}, {target_height=}")

            return x, y

        def _clip_left_for_resize(self, w: ui.Window, x: float, width: float, direction: Direction) -> Tuple[int, int, bool]:
            resize_left_limit_reached = False

            screen_x = w.screen.visible_rect.x

            # clip to screen
            if x < screen_x and direction['left']:
                # print(f'_clip_left: left clipping')

                # update width before updating new_x
                width = width - (x - screen_x)
                x = screen_x

                resize_left_limit_reached = True

                if testing:
                    print(f'_clip_left_for_resize: {resize_left_limit_reached=}')

            return x, width, resize_left_limit_reached

        def _clip_up_for_resize(self, w: ui.Window, y: float, height: float, direction: Direction) -> Tuple[int, int, bool]:
            resize_up_limit_reached = False

            screen_y = w.screen.visible_rect.y

            # clip to screen
            if y < screen_y and direction['up']:
                # print(f'_clip_up: up clipping')

                # update height before updating y
                height = height - (screen_y - y)
                y = screen_y

                resize_up_limit_reached = True

                if testing:
                    print(f'_clip_up_for_resize: {resize_up_limit_reached=}')

            return y, height, resize_up_limit_reached

        def _clip_right_for_resize(self, w: ui.Window, x: float, width: float, direction: Direction) -> Tuple[int, int, bool]:
            resize_right_limit_reached = False

            screen_x = w.screen.visible_rect.x
            screen_width = w.screen.visible_rect.width

            if x + width > screen_x + screen_width and direction['right']:
                # print(f'_clip_right: right clipping')

                width = screen_x + screen_width - x

                if testing:
                    print(f'_clip_right_for_resize: {resize_right_limit_reached=}')

                resize_right_limit_reached = True

            return x, width, resize_right_limit_reached

        def _clip_down_for_resize(self, w: ui.Window, y: float, height: float, direction: Direction) -> Tuple[int, int, bool]:
            resize_down_limit_reached = False

            screen_y = w.screen.visible_rect.y
            screen_height = w.screen.visible_rect.height

            if y + height > screen_y + screen_height and direction['down']:
                # print(f'_clip_down: down clipping')

                height = screen_y + screen_height - y

                resize_down_limit_reached = True

                if testing:
                    print(f'_clip_right_for_resize: {resize_down_limit_reached=}')

            return y, height, resize_down_limit_reached

        def _win_resize_pixels_relative(self, w: ui.Window, delta_width: float, delta_height: float, direction_in: Direction) -> Tuple[bool, bool, bool, bool, bool]:
            start_time = time.time_ns()

            result = resize_left_limit_reached = resize_up_limit_reached = resize_right_limit_reached = resize_down_limit_reached = False

            # start with the current values
            x = new_x = w.rect.x
            y = new_y = w.rect.y
            width = w.rect.width
            height = w.rect.height
            new_width = width + delta_width
            new_height = height + delta_height

            if testing:
                    print(f'_win_resize_pixels_relative: starting {delta_width=}, {delta_height=}')

            # invert directions when shrinking non-uniformly. that is, we are shrinking *toward*
            #  the given direction rather than shrinking away from that direction.
            direction = direction_in.copy()
            if not all(direction.values()):
                if delta_width < 0:
                    temp = direction["right"]
                    direction["right"] = direction["left"]
                    direction["left"] = temp
                    # print(f'_win_resize_pixels_relative: swapped left and right')
                #
                if delta_height < 0:
                    temp = direction["up"]
                    direction["up"] = direction["down"]
                    direction["down"] = temp
                    # print(f'_win_resize_pixels_relative: swapped up and down')

            # are we moving diagonally?
            direction_count = sum(direction.values())

            if direction_count == 1:    # horizontal or vertical
                # print(f'_win_resize_pixels_relative: single direction (horizontal or vertical)')
                # apply changes as indicated
                if direction["left"]:
                    new_x = new_x - delta_width
                    new_x, new_width, resize_left_limit_reached = self._clip_left_for_resize(w, new_x, new_width, direction)
                #
                if direction["up"]:
                    new_y = new_y - delta_height
                    new_y, new_height, resize_up_limit_reached = self._clip_up_for_resize(w, new_y, new_height, direction)
                #
                if direction["right"]:
                    new_x, new_width, resize_right_limit_reached = self._clip_right_for_resize(w, new_x, new_width, direction)
                #
                if direction["down"]:
                    new_height = new_height + delta_height
                    new_y, new_height, resize_down_limit_reached = self._clip_down_for_resize(w, new_y, new_height, direction)

            elif direction_count == 2:    # stretch diagonally
                if direction["left"] and direction["up"]:
                    # we are stretching northwest so the coordinates must not change for the southeastern corner
                    new_x = new_x - delta_width
                    new_y = new_y - delta_height

                    new_x, new_width, resize_left_limit_reached = self._clip_left_for_resize(w, new_x, new_width, direction)
                    new_y, new_height, resize_up_limit_reached = self._clip_up_for_resize(w, new_y, new_height, direction)

                    #print(f'_win_resize_pixels_relative: left and up')

                elif direction["right"] and direction["up"]:
                    # we are stretching northeast so the coordinates must not change for the southwestern corner

                    # adjust y to account for the entire change in height
                    new_y = new_y - delta_height

                    new_x, new_width, resize_right_limit_reached = self._clip_right_for_resize(w, new_x, new_width, direction)
                    new_y, new_height, resize_up_limit_reached = self._clip_up_for_resize(w, new_y, new_height, direction)

                    #print(f'_win_resize_pixels_relative: right and up')

                elif direction["right"] and direction["down"]:
                    # we are stretching southeast so the coordinates must not change for the northwestern corner,
                    # nothing to do here x and y are already set correctly for this case
                    new_x, new_width, resize_right_limit_reached = self._clip_right_for_resize(w, new_x, new_width, direction)
                    new_y, new_height, resize_down_limit_reached = self._clip_down_for_resize(w, new_y, new_height, direction)

                    #print(f'_win_resize_pixels_relative: right and down')

                elif direction["left"] and direction["down"]:
                    # we are stretching southwest so the coordinates must not change for the northeastern corner,
                    # adjust x to account for the entire change in width
                    new_x = new_x - delta_width

                    new_x, new_width, resize_left_limit_reached = self._clip_left_for_resize(w, new_x, new_width, direction)
                    new_y, new_height, resize_down_limit_reached = self._clip_down_for_resize(w, new_y, new_height, direction)

                    #print(f'_win_resize_pixels_relative: left and down')

            elif direction_count == 4:    # stretch from center
                if abs(delta_width) >= 2 and abs(delta_height) >= 2:
                    # normal case, delta values are divisible by two
                    new_x = new_x - delta_width / 2
                    new_y = new_y - delta_height / 2
                else:
                    # alternate changing size and position, since we can only do one or the other when the delta is less than 2
                    if self.continuous_resize_alternation == 'size':
                        # change position this time
                        new_x = new_x - delta_width
                        new_y = new_y - delta_height

                        # remove delta from the size values
                        new_width = width
                        new_height = height

                        self.continuous_resize_alternation = 'position'
                    else:
                        # change size this time...nothing to actually do other than flip the toggle
                        self.continuous_resize_alternation = 'size'

                new_x, new_width, resize_left_limit_reached = self._clip_left_for_resize(w, new_x, new_width, direction)

                new_y, new_height, resize_up_limit_reached = self._clip_up_for_resize(w, new_y, new_height, direction)

                new_x, new_width, resize_right_limit_reached = self._clip_right_for_resize(w, new_x, new_width, direction)

                new_y, new_height, resize_down_limit_reached = self._clip_down_for_resize(w, new_y, new_height, direction)

                #print(f'_win_resize_pixels_relative: from center')

            # if testing:
            #     print(f'_win_move_pixels_relative: {delta_x=}, {delta_y=}, {delta_width=}, {delta_height=}')

            if testing:
                print(f'_win_resize_pixels_relative: {width=}, {new_width=}, {height=}, {new_height=}')

            # rounding
            round_x = round(x)
            round_y = round(y)
            round_width = round(width)
            round_height = round(height)
            #
            new_round_x = round(new_x)
            new_round_y = round(new_y)
            new_round_width = round(new_width)
            new_round_height = round(new_height)

            old_values = (round_x, round_y, round_width, round_height)
            new_values = (new_round_x, new_round_y, new_round_width, new_round_height)

            if testing:
                print(f'_win_resize_pixels_relative: setting rect {new_values=}')

            # make it so
            result = self.compass_control._win_set_rect(w, ui.Rect(*new_values))

            if testing:
                print(f'_win_resize_pixels_relative: self.compass_control._win_set_rect returned {result=}')

                diff_x = w.rect.x - round_x
                diff_y = w.rect.y - round_y
                diff_width = round_width - new_round_width
                diff_height = round_height - new_round_height
                print(f'_win_resize_pixels_relative: change: {diff_x=}, {diff_y=}, {diff_width=}, {diff_height=}')

            if not result:
                # shrink is a special case, need to detect when the window has shrunk to a minimum by
                # watching expected values to see when they stop changing as requested.
                if self.continuous_resize_width_increment < 0:
                    if w.rect.x != new_round_x or w.rect.width != new_round_width:
                        resize_left_limit_reached = True
                        resize_right_limit_reached = True
                        if testing:
                            print(f'_win_resize_pixels_relative: horizontal shrink limit reached')

                if self.continuous_resize_height_increment < 0:
                    if w.rect.y != new_round_y or w.rect.height != new_round_height:
                        resize_up_limit_reached = True
                        resize_down_limit_reached = True
                        if testing:
                            print(f'_win_resize_pixels_relative: vertical shrink limit reached')

            elapsed_time_ms = (time.time_ns() - start_time) / 1e6
            if testing:
                print(f'_win_resize_pixels_relative: done ({elapsed_time_ms} ms)')

            return result, resize_left_limit_reached, resize_up_limit_reached, resize_right_limit_reached, resize_down_limit_reached



    # CompassControl methods

    # Bresenham line code, from
    #       https://github.com/encukou/bresenham/blob/master/bresenham.py
    def bresenham(self, x0, y0, x1, y1):
        """Yield integer coordinates on the line from (x0, y0) to (x1, y1).

        Input coordinates should be integers.

        The result will contain both the start and the end point.
        """
        dx = x1 - x0
        dy = y1 - y0

        xsign = 1 if dx > 0 else -1
        ysign = 1 if dy > 0 else -1

        dx = abs(dx)
        dy = abs(dy)

        if dx > dy:
            xx, xy, yx, yy = xsign, 0, 0, ysign
        else:
            dx, dy = dy, dx
            xx, xy, yx, yy = 0, ysign, xsign, 0

        D = 2*dy - dx
        y = 0

        for x in range(dx + 1):
            yield x0 + x*xx + y*yx, y0 + x*xy + y*yy
            if D >= 0:
                y += 1
                D -= 2*dx
            D += 2*dy

    def _reset_continuous_flags(self) -> None:
        with self.continuous_mutex:
            self.mover._reset_continuous_flags()
            self.sizer._reset_continuous_flags()
            
            self.continuous_direction = None
            self.continuous_old_rect = None

    def _get_screen_edge_midpoint(self, screen: ui.Screen, direction: Direction) -> Tuple[float, float]:
        x = y = None

        direction_count = sum(direction.values())
        if direction_count == 1:
            if direction['left']: # west
                x = screen.rect.x
                y = (screen.rect.y + screen.rect.height) // 2
            elif direction['up']: # north
                x = (screen.rect.x + screen.rect.width) // 2
                y = screen.rect.y
            elif direction['right']: # east
                x = screen.rect.x + screen.rect.width
                y = (screen.rect.y + screen.rect.height) // 2
            elif direction['down']: # south
                x = (screen.rect.x + screen.rect.width) // 2
                y = screen.rect.y + screen.rect.height

        return x, y

    def _get_screen_corner(self, screen: ui.Screen, direction: Direction) -> Tuple[float, float]:
        x = y = None

        direction_count = sum(direction.values())
        if direction_count == 2:
            if direction['left'] and direction['up']: # northwest
                x = screen.rect.x
                y = screen.rect.y
            elif direction['right'] and direction['up']: # northeast
                x = screen.rect.x + screen.rect.width
                y = screen.rect.y
            elif direction['right'] and direction['down']: # southeast
                x = screen.rect.x + screen.rect.width
                y = screen.rect.y + screen.rect.height
            elif direction['left'] and direction['down']: # southwest
                x = screen.rect.x
                y = screen.rect.y + screen.rect.height

        return x, y

    def _get_screen_center(self, screen: ui.Screen) -> Tuple[float, float]:
        return screen.visible_rect.center.x, screen.visible_rect.center.y

    def _get_target_point(self, w: ui.Window, direction: Direction) -> Tuple[int, int]:
        screen = w.screen
        target_x = target_y = None

        direction_count = sum(direction.values())
        if direction_count == 1:    # horizontal or vertical
            target_x, target_y = self._get_screen_edge_midpoint(screen, direction)
        elif direction_count == 2:    # diagonal
            target_x, target_y = self._get_screen_corner(screen, direction)
        elif direction_count == 4:    # center
            target_x, target_y = self._get_screen_center(screen)

        return round(target_x), round(target_y)

    def _win_stop(self) -> None:
        with self.continuous_mutex:
            if not self.mover.continuous_move_job and not self.sizer.continuous_resize_job:
                if testing:
                    print('_win_stop: no jobs to stop (may have stopped automatically via clipping logic)')
                return

            if testing:
                print(f'_win_stop: current thread = {threading.get_native_id()}')

            if self.mover.continuous_move_job:
                cron.cancel(self.mover.continuous_move_job)

            if self.sizer.continuous_resize_job:
                cron.cancel(self.sizer.continuous_resize_job)

            # WIP - below call does not work for some reason
            # ctx.tags.remove(self.continuous_tag_name_qualified)
            ctx.tags = []

            if self.continuous_old_rect:
                # remember starting rectangle
                if testing:
                    print(f'_win_stop: {self.continuous_old_rect=}')

                self.last_window = {
                    'id': ui.active_window().id,
                    'rect': self.continuous_old_rect
                }
                self.continuous_old_rect = None

            self._reset_continuous_flags()

            _win_stop_gui.hide()

    def _get_diagonal_length(self, rect: ui.Rect) -> Tuple[int, int]:
        return math.sqrt(((rect.width - rect.x) ** 2) + ((rect.height - rect.y) ** 2))

    def _get_center_to_center_rect(self, w: ui.Window) -> ui.Rect:
        width = w.rect.width
        height = w.rect.y

        window_center = w.rect.center

        screen = w.screen
        screen_center = screen.visible_rect.center

        width = abs(window_center.x - screen_center.x)
        horizontal_multiplier = 1 if window_center.x <= screen_center.x else -1

        height = abs(window_center.y - screen_center.y)
        vertical_multiplier = 1 if window_center.y <= screen_center.y else -1

        center_to_center_rect = ui.Rect(round(screen_center.x), round(window_center.y), round(width), round(height))
        print(f'_get_center_to_center_rect: returning {center_to_center_rect=}, {horizontal_multiplier=}, {vertical_multiplier=}')

        return center_to_center_rect, horizontal_multiplier, vertical_multiplier

    def _get_component_dimensions(self, w: ui.Window, distance: float, direction: Direction, operation: str) -> Tuple[int, int]:
        delta_width = delta_height = 0
        rect = w.rect
        direction_count = sum(direction.values())
        if operation == 'move' and direction_count == 4:    # move to center
            # this is a special case - 'move center' - we return signed values for this case

            rect, horizontal_multiplier, vertical_multiplier = self._get_center_to_center_rect(w)
            diagonal_length = self._get_diagonal_length(rect)

            window_center = w.rect.center

            screen = w.screen
            screen_center = screen.visible_rect.center

            # from https://math.stackexchange.com/questions/175896/finding-a-point-along-a-line-a-certain-distance-away-from-another-point
            ratio_of_differences = distance / diagonal_length
            new_x = (((1 - ratio_of_differences) * window_center.x) + (ratio_of_differences * screen_center.x))
            new_y = (((1 - ratio_of_differences) * window_center.y) + (ratio_of_differences * screen_center.y))

            if testing:
                print(f"_get_component_dimensions: {diagonal_length=}, {new_x=}, {new_y=}")

            delta_width = abs(new_x - window_center.x) * horizontal_multiplier
            delta_height = abs(new_y - window_center.y) * vertical_multiplier

            if testing:
                x_steps = 0
                if delta_width != 0:
                    x_steps = rect.width/delta_width
                print(f"_get_component_dimensions: x steps={x_steps}")

                y_steps = 0
                if delta_height != 0:
                    y_steps = rect.height/delta_height
                print(f"_get_component_dimensions: y steps={y_steps}")
        else:
            if direction_count > 1:    # diagonal
                diagonal_length = self._get_diagonal_length(rect)
                ratio = distance / diagonal_length
                delta_width = rect.width * ratio
                delta_height = rect.height * ratio
            else:  # horizontal or vertical
                if direction["left"] or direction["right"]:
                    delta_width = distance
                elif direction["up"] or direction["down"]:
                    delta_height = distance

        if testing:
            print(f"_get_component_dimensions: returning {delta_width}, {delta_height}")

        return delta_width, delta_height

    def _get_component_dimensions_by_percent(self, w: ui.Window, percent: float, direction: Direction, operation: str) -> Tuple[int, int]:
        if testing:
            print(f'_get_component_dimensions_by_percent: {percent=}')

        rect = w.rect
        direction_count = sum(direction.values())
        if operation == 'move' and direction_count == 4:    # move to center
            rect, *unused = self._get_center_to_center_rect(w)

        if direction_count  > 1:    # diagonal
            diagonal_length = self._get_diagonal_length(rect)
            distance = diagonal_length * (percent/100)
        else:  # horizontal or vertical
            if direction["left"] or direction["right"]:
                distance = rect.width * (percent/100)
            elif direction["up"] or direction["down"]:
                distance =  rect.height * (percent/100)

        return self._get_component_dimensions(w, distance, direction, operation)

    def _get_continuous_parameters(self, w: ui.Window, rate_cps: float, direction: Direction, operation: str, frequency: str) -> Tuple[int, int]:
        if testing:
            print(f'get_continuous_parameters: {rate_cps=}')

        # convert rate from centimeters to inches, to match dpi units
        rate_ips = rate_cps / 2.54

        dpi_x = w.screen.dpi_x
        dpi_y = w.screen.dpi_y

        # calculate dots per millisecond
        dpms_x = (rate_ips * dpi_x) / 1000
        dpms_y = (rate_ips * dpi_y) / 1000

        if testing:
            print(f'get_continuous_parameters: {dpms_x=}, {dpms_y=}')

        width_increment = height_increment = 0

        direction_count = sum(direction.values())
        if direction_count > 1:    # diagonal
            width_increment = dpms_x * frequency
            height_increment = dpms_y * frequency

            if direction_count == 4 and operation == 'move':    # move to center
                if testing:
                    print(f"compass_control.get_continuous_parameters: 'move center' special case")

                # special case, return signed values
                if w.rect.center.x > w.screen.rect.center.x:
                    width_increment *= -1
                #
                if w.rect.center.y > w.screen.rect.center.y:
                    height_increment *= -1
        else:
            # single direction
            if direction["left"] or direction["right"]:
                width_increment = dpms_x * frequency
            elif direction["up"] or direction["down"]:
                height_increment = dpms_y * frequency

        if testing:
            print(f"compass_control.get_continuous_parameters: returning {width_increment=}, {height_increment=}")

        return width_increment, height_increment

    def _win_set_rect(self, w: ui.Window, rect_in: ui.Rect) -> bool:
        start_time = time.time_ns()
        
        if not rect_in:
            raise ValueError('rect_in is None')

        retries = settings.get('user.win_set_retries')
        queue_timeout = settings.get('user.win_set_queue_timeout')

        # adapted from https://talonvoice.slack.com/archives/C9MHQ4AGP/p1635971780355900
        q = queue.Queue()
        def on_move(event_win: ui.Window) -> None:
            if event_win == w and w.rect != old_rect:
                q.put(1)
                if testing:
                    print(f'_win_set_rect: win position changed')

        def on_resize(event_win: ui.Window) -> None:
            if event_win == w and w.rect != old_rect:
                q.put(1)
                if testing:
                    print(f'_win_set_rect: win size changed')

        if testing:
            print(f'_win_set_rect: starting...')
        #
        old_rect = w.rect
        result = False
        while retries >= 0:
            event_count = 0
            if (rect_in.x, rect_in.y) != (w.rect.x, w.rect.y):
                # print(f'_win_set_rect: register win_move')
                ui.register('win_move', on_move)
                event_count += 1
            if (rect_in.width, rect_in.height) != (w.rect.width, w.rect.height):
                ui.register('win_resize', on_resize)
                # print(f'_win_set_rect: register win_resize')
                event_count += 1
            if event_count == 0:
                # no real work to do
                result = True

                if testing:
                    print('_win_set_rect: nothing to do, window already matches given rect.')

                break

            start_time_rect = time.time_ns()
            w.rect = rect_in
            try:
                # for testing
                #raise queue.Empty()
                #raise Exception('just testing')

                q.get(timeout=queue_timeout)
                if event_count == 2:
                    q.get(timeout=queue_timeout)

            except queue.Empty:
                if testing:
                    print('_win_set_rect: timed out waiting for window update.')

                if retries > 0:
                    if testing:
                        print('_win_set_rect: retrying after time out...')
                    retries -= 1
                else:
                    if testing:
                        print('_win_set_rect: no more retries, failed')
            except:
                log_exception(f'{sys.exc_info()[1]}')
            else:
                if testing:
                    print(f'_win_set_rect: before: {old_rect}')
                    print(f'_win_set_rect: requested: {rect_in}')
                    print(f'_win_set_rect: after: {w.rect}')

                result = True

                # results are not guaranteed, warn if the request could not be fulfilled exactly
                if (rect_in.x, rect_in.y) != (w.rect.x, w.rect.y):
                    result = False
                    if settings.get('user.win_verbose_warnings') != 0:
                        logging.warning(f'_win_set_rect: after update, window position does not exactly match request: {rect_in.x, rect_in.y} -> {w.rect.x, w.rect.y}')

                if (rect_in.width, rect_in.height) != (w.rect.width, w.rect.height):
                    # warning below disabled because it happens normally in the course of shrinking
                    # a window (when it has reached minimal size).
                    result = False
                    if settings.get('user.win_verbose_warnings') != 0:
                        logging.warning(f'_win_set_rect: after update, window size does not exactly match request: {rect_in.width, rect_in.height} -> {w.rect.width, w.rect.height}')

            finally:
                # remember old rectangle, for 'win revert'
                self.last_window = {
                    'id': w.id,
                    'rect': old_rect
                }

                ui.unregister('win_move',   on_move)
                ui.unregister('win_resize', on_resize)

        elapsed_time_ms = (time.time_ns() - start_time) / 1e6
        if testing:
            print(f'_win_set_rect: done ({elapsed_time_ms} ms)')

        return result


# globals
compass_control = CompassControl()            

## talon stuff

mod = Module()

mod.tag(compass_control.continuous_tag_name, desc="Enable stop command during continuous window move/resize.")

# context used to enable/disable window_tweak_running tag
ctx = Context()

# context containing the stop command, enabled only when a continuous move/resize is running
ctx_stop = Context()
ctx_stop.matches = fr"""
tag: user.{compass_control.continuous_tag_name}
"""

mod.setting(
    "win_move_frequency",
    type=str,
    default="30ms",
    desc="The update frequency used when moving a window continuously",
)
mod.setting(
    "win_resize_frequency",
    type=str,
    default="30ms",
    desc="The update frequency used when resizing a window continuously",
)
mod.setting(
    "win_continuous_move_rate",
    type=float,
    default=4.5,
    desc="The target speed, in cm/sec, for continuous move operations",
)
mod.setting(
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
mod.setting(
    "win_verbose_warnings",
    type=bool,
    default=False,
    # window move and resize requests are not guaranteed
    desc="Whether to generate a warning when the result of a window move or resize request does not exactly match the request.",
)

# taken from https: //talon.wiki/unofficial_talon_docs/#captures
@mod.capture(rule="center | ((north | south) [(east | west)] | east | west)")
def compass_direction(m: List) -> Direction:
    """
    Matches on a basic compass direction to return which keys should
    be pressed.
    """
    result = {}

    if "center" in m:
        result["up"] = result["down"] = result["right"] = result["left"] = True
    else:
        result = {
            "up": "north" in m,
            "down": "south" in m,
            "right": "east" in m,
            "left": "west" in m
        }

    if testing:
        print(f'compass_direction: {result=}')

    return result

# WIP - fix this when done testing
# @imgui.open(y=0)
@imgui.open(x=4000,y=244)
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

    gui.text(f"Width: {width}")
    gui.text(f"Height: {height}")

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
    gui.text(f"Top Left: {x, y}")
    gui.text(f"Top Right: {x + width, y}")
    gui.text(f"Bottom Left: {x, y + height}")
    gui.text(f"Bottom Right: {x + width, y + height}")
    gui.text(f"Center: {round(screen.visible_rect.center.x), round(screen.visible_rect.center.y)}")
    gui.spacer()

    gui.text(f"Width: {width}")
    gui.text(f"Height: {height}")

    gui.spacer()

    x = screen.rect.x
    y = screen.rect.y
    width = screen.rect.width
    height = screen.rect.height

    gui.text(f"__Physical Rectangle__")
    gui.text(f"Top Left: {x, y}")
    gui.text(f"Top Right: {x + width, y}")
    gui.text(f"Bottom Left: {x, y + height}")
    gui.text(f"Bottom Right: {x + width, y + height}")
    gui.text(f"Center: {round(screen.rect.center.x), round(screen.rect.center.y)}")
    gui.spacer()

    gui.text(f"Width: {width}")
    gui.text(f"Height: {height}")

    gui.line()

    gui.text(f"Say 'win hide' to close this window.")

    gui.line()

    if gui.button("Close"):
        _win_show_gui.hide()

@imgui.open(y=0)
def _win_stop_gui(gui: imgui.GUI) -> None:
    gui.text(f"Say 'win stop' or click below.")
    gui.line()
    if gui.button("Stop moving/resizing"):
        actions.user.win_stop()

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
        if testing:
            print('win_stop() not implemented in current context')
        pass

    def win_move(direction: Optional[Direction] = None) -> None:
        "Move window in small increments in the given direction, until stopped"
        w = ui.active_window()
        compass_control.mover._win_move_continuous(w, direction)

    def win_move_absolute(x_in: float, y_in: float, region: Optional[Direction] = None) -> None:
        "Move window to given absolute position, centered on the point indicated by the given region"

        w = ui.active_window()
        x = x_in
        y = y_in

        # find the point which we will move to the given coordinates, as indicated by the region.
        if region:
            x, y = compass_control.mover._translate_top_left_by_region_for_move(w, x, y, region)

            if testing:
                print(f'win_move_absolute: translated top left position: {x,y}')

        compass_control._win_set_rect(w, ui.Rect(round(x), round(y), round(w.rect.width), round(w.rect.height)))

        if testing:
            print(f'win_move_absolute: {w.rect=}')
            ctrl.mouse_move(x_in, y_in)

    def win_stretch(direction: Optional[Direction] = None) -> None:
        "Stretch window in small increments until stopped, optionally in the given direction"

        if not direction:
            direction = compass_direction(['center'])

        w = ui.active_window()
        compass_control.sizer._win_resize_continuous(w, 1, direction)

    def win_shrink(direction: Optional[Direction] = None) -> None:
        "Shrink window in small increments until stopped, optionally in the given direction"
        w = ui.active_window()

        if not direction:
            direction = compass_direction(['center'])

        compass_control.sizer._win_resize_continuous(w, -1, direction)

    def win_resize_absolute(target_width: float, target_height: float, region_in: Optional[Direction] = None) -> None:
        "Size window to given absolute dimensions, optionally by stretching/shrinking in the direction indicated by the given region"
        w = ui.active_window()

        x = w.rect.x
        y = w.rect.y
        delta_width = target_width - w.rect.width
        delta_height = target_height - w.rect.height

        region = None
        if region_in:
            # find the point which we will move to the given coordinates, as indicated by the given region.

            region = region_in.copy()
            # invert directions when shrinking. that is, we are shrinking *toward* the
            #  given direction rather than shrinking away from that direction.
            if delta_width < 0:
                region["left"] = region_in["right"]
                region["right"] = region_in["left"]
            #
            if delta_height < 0:
                region["up"] = region_in["down"]
                region["down"] = region_in["up"]

            x, y = compass_control.sizer._translate_top_left_by_region_for_resize(w, target_width, target_height, region)

            if testing:
                print(f'win_resize_absolute: translated top left position: {x,y}')

        compass_control._win_set_rect(w, ui.Rect(round(x), round(y), round(target_width), round(target_height)))

        if testing:
            print(f'win_resize_absolute: {w.rect=}')
            ctrl.mouse_move(w.rect.x, w.rect.y)

    def win_move_pixels(distance: int, direction: Direction) -> None:
        "move window some number of pixels"

        w = ui.active_window()

        delta_width, delta_height = compass_control._get_component_dimensions(w, distance, direction, 'move')

        return compass_control.mover._win_move_pixels_relative(w, delta_width, delta_height, direction)

    def win_move_percent(percent: float, direction: Direction) -> None:
        "move window some percentage of the current size"

        w = ui.active_window()

        delta_width, delta_height = compass_control._get_component_dimensions_by_percent(w, percent, direction, 'move')

        return compass_control.mover._win_move_pixels_relative(w, delta_width, delta_height, direction)

# WIP - move action method logic into classes

    def win_resize_pixels(distance: int, direction: Direction) -> None:
        "change window size by pixels"
        w = ui.active_window()

        delta_width, delta_height = compass_control._get_component_dimensions(w, distance, direction, 'resize')

        if testing:
            print(f'win_resize_pixels: {delta_width=}, {delta_height=}')

        compass_control.sizer._win_resize_pixels_relative(w, delta_width, delta_height, direction)

    def win_resize_percent(percent: float, direction: Direction) -> None:
        "change window size by a percentage of current size"

        w = ui.active_window()

        delta_width, delta_height = compass_control._get_component_dimensions_by_percent(w, percent, direction, 'resize')

        if testing:
            print(f'win_resize_percent: {delta_width=}, {delta_height=}')

        compass_control.sizer._win_resize_pixels_relative(w, delta_width, delta_height, direction)

    def win_snap_percent(percent: int) -> None:
        "center window and change size to given percentage of parent screen (in each direction)"

        direction = compass_direction(['center'])

        w = ui.active_window()

        target_width = (w.screen.visible_rect.width * (percent/100))
        target_height = (w.screen.visible_rect.height * (percent/100))

        # move window center to screen center
        actions.user.win_move_absolute(w.screen.visible_rect.center.x, w.screen.visible_rect.center.y, direction)

        # set window size
        actions.user.win_resize_absolute(target_width, target_height, direction)

    def win_revert() -> None:
        "restore current window's last remembered size and position"

        w = ui.active_window()

        if compass_control.last_window and compass_control.last_window['id'] == w.id:
            if testing:
                print(f'win_revert: reverting size and/or position for {compass_control.last_window}')
            compass_control._win_set_rect(w, compass_control.last_window['rect'])

    def win_test_bresenham(num: int) -> None:
        "test modified bresenham algo"

        if num == 1:
            compass_control.mover._win_test_bresenham_1()

@ctx_stop.action_class("user")
class WindowTweakActions:
    """
    # Commands for controlling continuous window move/resize operations
    """
    def win_stop() -> None:
        "Stops current window move/resize operation"
        compass_control._win_stop()