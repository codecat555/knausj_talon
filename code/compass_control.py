# """
# Tools for managing the size and position of things using cardinal and ordinal directions, e.g. North, Southwest, etc.

# Continuous move/resize machinery adapted from mouse.py.
# """

# # WIP - split classes into generic versions that only understand rects and those that handle windows

# # WIP - 'win snap 200 percent' moves rectangle up a bit, turns out talon resize() API will not increase
# # WIP - height beyond 1625 for some reason...perhaps because the largest of my 3 screens is height 1600?

from typing import Any, Callable, Dict, List, Tuple, Optional, Iterator

import math
import queue
import logging
import threading
import time

from talon import ui, Module, ctrl #, Context, actions, imgui, cron, settings
# from talon.types.point import Point2d
# from talon.debug import log_exception

# a type for representing compass directions
Direction = Dict[str, bool]

# turn debug messages on and off
testing: bool = True

class CompassControl:
    class RectUpdateError(Exception):
        def __init__(self, requested, actual):
            self.requested = requested
            self.actual = actual
        
    def _handle_rect_update_error(self, e: RectUpdateError) -> None:
        if settings.get('user.compass_control_verbose_warnings') != 0:
            position_matches_request = (e.requested.x, e.requested.y) == (e.actual.x, e.actual.y)
            size_matches_request = (e.requested.width, e.requested.height) == (e.actual.width, e.actual.height)

            if not position_matches_request:
                logging.warning(f'after update, rectangle size does not exactly match request: {e.requested.width, e.requested.height} -> {e.actual.width, e.actual.height}')
        
            if not size_matches_request:
                logging.warning(f'after update, rectangle position does not exactly match request: {e.requested.x, e.requested.y} -> {e.actual.x, e.actual.y}')

    def __init__(self, continuous_tag_name: str, set_method: Callable):
        # tag used to enable/disable commands used during continuous move/resize operations
        self.continuous_tag_name: str = continuous_tag_name
        self.continuous_tag_name_qualified: str = 'user.' + self.continuous_tag_name

        self.set_method = set_method

        # remember the last rectangle so we can always revert back to it later
        self.last_rect: Dict = dict()

        self.continuous_direction: Direction = None
        self.continuous_old_rect: ui.Rect = None
        self.continuous_mutex: threading.RLock = threading.RLock()
        self.continuous_iteration: int = 0

        self.mover: CompassControl.Mover = CompassControl.Mover(self)
        self.sizer: CompassControl.Sizer = CompassControl.Sizer(self)
        
    class Mover:
        def __init__(self, compass_control):
            self.compass_control: CompassControl = compass_control

            self.continuous_move_width_increment: int = 0
            self.continuous_move_height_increment: int = 0
            self.continuous_move_job: Any = None
            self.continuous_bres: Iterator[(int, int)] = None

        def _reset_continuous_flags(self) -> None:
            with self.compass_control.continuous_mutex:
                self.continuous_move_width_increment = 0
                self.continuous_move_height_increment = 0
                self.continuous_move_job = None
                self.continuous_bres = None

        def continuous_helper(self) -> None:
            def _move_it(rect: ui.Rect, delta_x: float, delta_y: float, direction: Direction) -> bool:
                result, horizontal_limit_reached, vertical_limit_reached = self.move_pixels_relative(rect_cc, rect_id, delta_x, delta_y, self.compass_control.continuous_direction)
                if not result:
                    if testing:
                        print(f'continuous_helper: rectangle move failed. {result=}, {horizontal_limit_reached=}, {vertical_limit_reached=}')
                    self.compass_control.continuous_stop()
                    return False
                elif (horizontal_limit_reached and vertical_limit_reached):
                    if testing:
                        print(f'continuous_helper: rectangle move is complete. {result=}, {horizontal_limit_reached=}, {vertical_limit_reached=}')
                    self.compass_control.continuous_stop()
                    return False
                else:
                    if horizontal_limit_reached:
                        self.continuous_move_width_increment = 0

                    if vertical_limit_reached:
                        self.continuous_move_height_increment = 0

                return True

            start_mutex_wait = time.time_ns()

            with self.compass_control.continuous_mutex:
                iteration = self.compass_control.continuous_iteration

                elapsed_time_ms = (time.time_ns() - start_mutex_wait) / 1e6
                if testing:
                    print(f'continuous_helper: iteration {iteration} mutex wait ({elapsed_time_ms} ms)')

                start_time = time.time_ns()

                # if testing:
                #     print(f'continuous_helper: current thread = {threading.get_native_id()}')

                if not self.continuous_move_job:
                    # seems sometimes this gets called while the job is being canceled, so just return in that case
                    return

                if testing:
                    print(f'continuous_helper: starting iteration {iteration} - {rect=}')

                if self.continuous_move_width_increment or self.continuous_move_height_increment:
                    direction_count = sum(self.compass_control.continuous_direction.values())
                    if direction_count != 4:
                        if not _move_it(rect_cc, rect_id, self.continuous_move_width_increment, self.continuous_move_height_increment, self.compass_control.continuous_direction):
                            if testing:
                                print(f'continuous_helper: move failed')
                    else:    # move to center (special case)
                        initial_x = rect.x
                        initial_y = rect.y
                        cumulative_delta_x = cumulative_delta_y = 0
                        center_x = center_y = 0
                        while True:
                            try:
                                center_x, center_y = next(self.continuous_bres)
                                # translate center coordinates to top left
                                x, y = self.translate_top_left_by_region(rect_cc, rect_id, center_x, center_y, self.compass_control.continuous_direction)
                                if testing:
                                        print(f'continuous_helper: next bresenham point = {center_x, center_y}, corresponding to top left = {x, y}')
                                        print(f'continuous_helper: current rectangle top left = {rect.x, rect.y}')
                                # skip until we see some movement
                                while (x, y) == (round(rect.x), round(rect.y)):
                                    center_x, center_y = next(self.continuous_bres)
                                    # translate center coordinates to top left
                                    x, y = self.translate_top_left_by_region(rect_cc, rect_id, center_x, center_y, self.compass_control.continuous_direction)
                                    if testing:
                                        print(f'continuous_helper: skipped to next bresenham point = {center_x, center_y}, corresponding to top left = {x, y}')
                            except StopIteration:
                                if testing:
                                    print(f'continuous_helper: StopIteration')

                                self.compass_control.continuous_stop()
                                
                                # return
                                break

                            delta_x = abs(x - rect.x)
                            if self.continuous_move_width_increment < 0:
                                delta_x *= -1

                            delta_y = abs(y - rect.y)
                            if self.continuous_move_height_increment < 0:
                                delta_y *= -1

                            if testing:
                                print(f'continuous_helper: stepping from {rect.x, rect.y} to {x, y}, {delta_x=}, {delta_y=}')

                            if not _move_it(rect_cc, rect_id, delta_x, delta_y, self.compass_control.continuous_direction):
                                if testing:
                                    print(f'continuous_helper: move failed')
                                return

                            cumulative_delta_x = abs(rect.x - initial_x)
                            if testing:
                                print(f'continuous_helper: {cumulative_delta_x=}, {self.continuous_move_width_increment=}')
                            if self.continuous_move_width_increment != 0 and cumulative_delta_x >= abs(self.continuous_move_width_increment):
                                if testing:
                                    print(f'continuous_helper: reached horizontal limit for current iteration, stopping')
                                break

                            cumulative_delta_y = abs(rect.y - initial_y)
                            if testing:
                                print(f'continuous_helper: {cumulative_delta_y=}, {self.continuous_move_height_increment=}')
                            if self.continuous_move_height_increment != 0 and cumulative_delta_y >= abs(self.continuous_move_height_increment):
                                if testing:
                                    print(f'continuous_helper: reached vertical limit for current iteration, stopping')
                                break
                else:
                    # move increments are both zero, nothing to do...so stop
                    if testing:
                        print(f'continuous_helper: width and height increments are both zero, nothing to do, {rect=}')
                    self.compass_control.continuous_stop()

                elapsed_time_ms = (time.time_ns() - start_time) / 1e6
                if testing:
                    print(f'continuous_helper: iteration {iteration} done ({elapsed_time_ms} ms)')
                # frequency = float((self.move_frequency)[:-2])
                if elapsed_time_ms > self.frequency:
                    if self.verbose_warnings != 0:
                        logging.warning(f'continuous_helper: move iteration {iteration} took {elapsed_time_ms}ms, longer than the current move_frequency setting. actual rate may not match the continuous_move_rate setting.')

                self.compass_control.continuous_iteration += 1
            
        def _start_continuous(self) -> None:
            with self.compass_control.continuous_mutex:
                ctx.tags = [self.compass_control.continuous_tag_name_qualified]
                self.continuous_move_job = cron.interval(self.move_frequency, self.continuous_helper)
                if testing:
                    print(f'_start_continuous: {self.continuous_move_job=}')

        def init_continuous(self, rect_cc: ui.Rect, rect_id: int, direction: Direction) -> None:
            with self.compass_control.continuous_mutex:
                if self.continuous_move_job:
                    if testing:
                        print(f'init_continuous: {self.continuous_move_job=}')
                    logging.warning('cannot start a move job when one is already running')
                    return

                self.compass_control._reset_continuous_flags()

                self.compass_control.continuous_direction = direction

                self.compass_control.continuous_old_rect = rect

                # frequency = float((self.move_frequency)[:-2])
                rate = self.continuous_move_rate
                self.continuous_move_width_increment, self.continuous_move_height_increment = self.compass_control._get_continuous_parameters(rect_cc, rect_id, rate, direction, 'move', self.frequency)

                if testing:
                    print(f'init_continuous: {self.continuous_move_width_increment=}, {self.continuous_move_height_increment=}')

                direction_count = sum(self.compass_control.continuous_direction.values())
                if direction_count == 4:    # move to center (special case)
                    # follow path from rectangle center to parent rectangle center
                    x0 = round(rect.center.x)
                    y0 = round(rect.center.y)

                    x1, y1 = self.compass_control.get_target_point(rect_cc, rect_id, direction)

                    x = x_prev = x0
                    y = y_prev = y0

                    # note that this is based on the line from rectangle center to parent rectangle center, resulting
                    # coordinates will have to be translated to top left to set rectangle position, etc.
                    self.continuous_bres = self.compass_control.bresenham(x0, y0, x1, y1)

                    # discard initial point (we're already there)
                    first = next(self.continuous_bres)

                self._start_continuous()

                if self.hide_move_gui == 0:
                    _stop_gui.show()

        def _clip_to_fit(self, rect_cc: ui.Rect, rect_id: int, parent_rect: ui.Rect, x: float, y: float, width: float, height: float, direction: Direction) -> Tuple[int, int, bool, bool]:
            parent_x = parent_rect.x
            parent_y = parent_rect.y
            parent_width = parent_rect.width
            parent_height = parent_rect.height

            horizontal_limit_reached = vertical_limit_reached = False

            new_x = x
            new_y = y
            if x <= parent_x and direction["left"]:
                new_x = parent_x
                horizontal_limit_reached = True
            elif x >= parent_x + parent_width - width and direction["right"]:
                new_x = parent_x + parent_width - width
                horizontal_limit_reached = True

            if y <= parent_y and direction["up"]:
                new_y = parent_y
                vertical_limit_reached = True
            elif y >= parent_y + parent_height - height and direction["down"]:
                new_y = parent_y + parent_height - height
                vertical_limit_reached = True

            return round(new_x), round(new_y), horizontal_limit_reached, vertical_limit_reached

        def move_pixels_relative(self, rect_cc: ui.Rect, rect_id: int, parent_rect: ui.Rect, delta_x: float, delta_y: float, direction: Direction) -> Tuple[bool, bool, bool]:
            start_time = time.time_ns()

            result = horizontal_limit_reached = vertical_limit_reached = False

            # start with the current values
            x = rect.x
            y = rect.y

            if testing:
                print(f'move_pixels_relative: {delta_x=}, {delta_y=}, {x=}, {y=}')

            # apply changes as indicated
            direction_count = sum(direction.values())
            if direction_count < 4:
                if direction["left"]:
                    x -= delta_x

                if direction["right"]:
                    x += delta_x
                #
                if direction["up"]:
                    y -= delta_y

                if direction["down"]:
                    y += delta_y

                new_x, new_y, horizontal_limit_reached, vertical_limit_reached = self._clip_to_fit(rect_cc, rect_id, x, y, rect.width, rect.height, direction)
            else:    # move to center
                rect_width = rect.width
                rect_height = rect.height

                new_x = x + delta_x
                new_y = y + delta_y

                new_rect_center = Point2d(round(new_x + rect_width/2), round(new_y + rect_height/2))

                target_x = parent.center.x - rect_width/2
                target_y = parent.center.y - rect_height/2

                # calculate distance between rectangle center and parent center
                distance_x = parent.center.x - rect.center.x
                distance_y = parent.center.y - rect.center.y

                if testing:
                    print(f'move_pixels_relative: {new_x=}, {new_y=}, {parent.center.x=}, {parent.center.y=}')
                    print(f'move_pixels_relative: top left - {target_x=}, {target_y=}')

                if (delta_x != 0):
                    if testing:
                        print(f'move_pixels_relative: {distance_x=}, {delta_x=}')

                    if (delta_x < 0 and (distance_x >= delta_x)) or (delta_x > 0 and (distance_x <= delta_x)):
                        # crossed center point, done moving horizontally
                        if testing:
                            print(f'move_pixels_relative: crossed horizontal center point')
                        new_x = target_x
                        horizontal_limit_reached = True

                if delta_y != 0:
                    if testing:
                        print(f'move_pixels_relative: {distance_y=}, {delta_y=}')

                    if (delta_y < 0 and (distance_y >= delta_y)) or (delta_y > 0 and (distance_y <= delta_y)):
                        # crossed center point, done moving vertically
                        if testing:
                            print(f'move_pixels_relative: crossed vertical center point')
                        new_y = target_y
                        vertical_limit_reached = True

            result = False
            try:
                # make it so
                result = self.compass_control.set_rect(rect_cc, rect_id, ui.Rect(new_x, new_y, rect.width, rect.height))
            except CompassControl.RectUpdateError as e:
                self.compass_control._handle_rect_update_error(e)

            elapsed_time_ms = (time.time_ns() - start_time) / 1e6
            if testing:
                print(f'move_pixels_relative: done ({elapsed_time_ms} ms)')

            return result, horizontal_limit_reached, vertical_limit_reached

        # note: this method is used by move_absolute(), which interprets the Direction
        # argument differently than elsewhere in this module.
        def translate_top_left_by_region(self, rect_cc: ui.Rect, rect_id: int, target_x: float, target_y: float, region_in: Direction) -> Tuple[int, int]:

            width = rect.width
            height = rect.height

            if testing:
                print(f"_translate_top_left_by_region: initial rect: {rect}")
                print(f"_translate_top_left_by_region: move coordinates: {target_x=}, {target_y=}")

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
                print(f"_translate_top_left_by_region: translated position: {top_left_x=}, {top_left_y=}")

            return round(top_left_x), round(top_left_y)

        def move_absolute(self, rect_cc: ui.Rect, rect_id: int, x: float, y: float, region_in: Optional[Direction] = None) -> None:
                            # (w.rect,            w.id,       x,          y,      region)
                # find the point which we will move to the given coordinates, as indicated by the region.
                if region_in:
                    x, y = self.translate_top_left_by_region(rect_cc, rect_id, x, y, region_in)

                    if testing:
                        print(f'move_absolute: translated top left position: {x,y}')

                result = False
                try:
                    result = self.compass_control.set_rect(rect_cc, rect_id, ui.Rect(round(x), round(y), round(rect_cc.width), round(rect_cc.height)))
                except CompassControl.RectUpdateError as e:
                    self.compass_control._handle_rect_update_error(e)

                if testing:
                    print(f'move_absolute: {rect_cc=}')
                    ctrl.mouse_move(x, y)

        def test_bresenham_1(self):
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
                    print(f'test_bresenham_1: bresenham: {b0}')
            except StopIteration:
                print(f'test_bresenham_1: bresenham done')

    class Sizer:
        def __init__(self, compass_control):
            self.compass_control: CompassControl = compass_control
            
            self.continuous_resize_width_increment: int = 0
            self.continuous_resize_height_increment: int = 0
            self.continuous_resize_job: Any = None
            self.continuous_resize_alternation: str = None

        def _reset_continuous_flags(self) -> None:
            with self.compass_control.continuous_mutex:
                self.continuous_resize_width_increment = 0
                self.continuous_resize_height_increment = 0
                self.continuous_resize_job = None

        def continuous_helper(self) -> None:
            start_mutex_wait = time.time_ns()

            with self.compass_control.continuous_mutex:
                iteration = self.compass_control.continuous_iteration

                elapsed_time_ms = (time.time_ns() - start_mutex_wait) / 1e6
                if testing:
                    print(f'continuous_helper: mutex wait ({elapsed_time_ms} ms)')

                start_time = time.time_ns()

                if not self.continuous_resize_job:
                    # seems sometimes this gets called while the job is being canceled, so just return that case
                    return

                if testing:
                    print(f'continuous_helper: starting iteration {iteration} - {rect=}')

                if self.continuous_resize_width_increment or self.continuous_resize_height_increment:
                    result, resize_left_limit_reached, resize_up_limit_reached, resize_right_limit_reached, resize_down_limit_reached = self.resize_pixels_relative(rect_cc, rect_id, self.continuous_resize_width_increment, self.continuous_resize_height_increment, self.compass_control.continuous_direction)

                    if not result:
                        if testing:
                            print(f'continuous_helper: rectangle resize failed. {result=}')
                        self.compass_control.continuous_stop()
                    else:
                        # check limits
                        direction_count = sum(self.compass_control.continuous_direction.values())
                        if direction_count == 1:    # horizontal or vertical
                            if any([resize_left_limit_reached, resize_up_limit_reached, resize_right_limit_reached, resize_down_limit_reached]):
                                if testing:
                                    print(f'continuous_helper: single direction limit reached')
                                self.continuous_resize_width_increment = 0
                                self.continuous_resize_height_increment = 0
                        elif direction_count == 2:    # diagonal
                            if resize_left_limit_reached or resize_right_limit_reached:
                                if testing:
                                    print(f'continuous_helper: horizontal limit reached')
                                self.continuous_resize_width_increment = 0
                            #
                            if resize_up_limit_reached or resize_down_limit_reached:
                                if testing:
                                    print(f'continuous_helper: vertical limit reached')
                                self.continuous_resize_height_increment = 0
                        elif direction_count == 4:    # from center
                            if resize_left_limit_reached and resize_right_limit_reached:
                                if testing:
                                    print(f'continuous_helper: horizontal limit reached')
                                self.continuous_resize_width_increment = 0

                            if resize_up_limit_reached and resize_down_limit_reached:
                                if testing:
                                    print(f'continuous_helper: vertical limit reached')
                                self.continuous_resize_height_increment = 0
                else:
                    # resize increments are both zero, nothing to do...so stop
                    if testing:
                        print('continuous_helper: rectangle resize is complete')
                    self.compass_control.continuous_stop()

            elapsed_time_ms = (time.time_ns() - start_time) / 1e6
            if testing:
                print(f'continuous_helper: iteration {iteration} done ({elapsed_time_ms} ms)')
            # frequency = float(( self.frequency)[:-2])
            if elapsed_time_ms > self.frequency:
                if self.verbose_warnings != 0:
                    logging.warning(f'continuous_helper: resize iteration {iteration} took {elapsed_time_ms}ms, longer than the current resize_frequency setting. actual rate may not match the continuous_resize_rate setting.')

            # for testing
            one_loop_only = False
            if one_loop_only:
                self.compass_control.continuous_stop()

            self.compass_control.continuous_iteration += 1

        def _start_continuous(self) -> None:
            with self.compass_control.continuous_mutex:
                ctx.tags = [self.compass_control.continuous_tag_name_qualified]
                self.continuous_resize_job = cron.interval( self.frequency, self.continuous_helper)

        def init_continuous(self, rect_cc: ui.Rect, rect_id: int, multiplier: int, direction: Optional[Direction] = None) -> None:
            with self.compass_control.continuous_mutex:
                if self.continuous_resize_job:
                    logging.warning('cannot start a resize job when one is already running')
                    return

                # frequency = float(( self.frequency)[:-2])
                rate = self.continuous_resize_rate
                self.continuous_resize_width_increment, self.continuous_resize_height_increment = self.compass_control._get_continuous_parameters(rect_cc, rect_id, rate, direction, '_resize',  self.frequency)

                # apply multiplier to control whether we're stretching or shrinking
                self.continuous_resize_width_increment *= multiplier
                self.continuous_resize_height_increment *= multiplier

                self.compass_control.continuous_direction = direction

                self.compass_control.continuous_old_rect = rect

                if testing:
                    print(f'init_continuous: starting resize - {self.continuous_resize_width_increment=}, {self.continuous_resize_height_increment=}, {self.compass_control.continuous_direction=}, {multiplier=}')

                self._start_continuous()

                if self.hide_resize_gui == 0:
                    _stop_gui.show()

        def translate_top_left_by_region(self, rect_cc: ui.Rect, rect_id: int, target_width: float, target_height: float, direction: Direction) -> Tuple[int, int]:

            x = rect.x
            y = rect.y

            delta_width = target_width - rect.width
            delta_height = target_height - rect.height

            if self.verbose_warnings != 0:
                if abs(delta_width) < 2:
                    logging.warning(f'_translate_top_left_by_region: width change is less than 2, which is too small for normal resize calculations: {delta_width=}')
                if abs(delta_height) < 2:
                    logging.warning(f'_translate_top_left_by_region: height change is less than 2, which is too small for normal resize calculations: {delta_height=}')

            if testing:
                print(f"_translate_top_left_by_region: initial rect: {rect}")
                print(f"_translate_top_left_by_region: resize coordinates: {target_width=}, {target_height=}")

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
                print(f"_translate_top_left_by_region: translated position: {x=}, {y=}, {target_width=}, {target_height=}")

            return round(x), round(y)

        def _clip_left(self, rect_cc: ui.Rect, rect_id: int, parent_rect: ui.Rect, x: float, width: float, direction: Direction) -> Tuple[int, int, bool]:
            resize_left_limit_reached = False

            # clip to parent rectangle
            if x < parent_rect.x and direction['left']:
                # print(f'_clip_left: left clipping')

                # update width before updating new_x
                width = width - (x - parent_rect.x)
                x = parent_rect.x

                resize_left_limit_reached = True

                if testing:
                    print(f'_clip_left: {resize_left_limit_reached=}')

            return round(x), round(width), resize_left_limit_reached

        def _clip_up(self, rect_cc: ui.Rect, rect_id: int, parent_rect: ui.Rect, y: float, height: float, direction: Direction) -> Tuple[int, int, bool]:
            resize_up_limit_reached = False

            # clip to parent rectangle
            if y < parent_rect.y and direction['up']:
                # print(f'_clip_up: up clipping')

                # update height before updating y
                height = height - (parent_rect.y - y)
                y = parent_rect.y

                resize_up_limit_reached = True

                if testing:
                    print(f'_clip_up: {resize_up_limit_reached=}')

            return round(y), round(height), resize_up_limit_reached

        def _clip_right(self, rect_cc: ui.Rect, rect_id: int, parent_rect: ui.Rect, x: float, width: float, direction: Direction) -> Tuple[int, int, bool]:
            resize_right_limit_reached = False

            if x + width > parent_rect.x + parent_rect.width and direction['right']:
                # print(f'_clip_right: right clipping')

                width = parent_rect.x + parent_rect.width - x

                if testing:
                    print(f'_clip_right: {resize_right_limit_reached=}')

                resize_right_limit_reached = True

            return round(x), round(width), resize_right_limit_reached

        def _clip_down(self, rect_cc: ui.Rect, rect_id: int, parent_rect: ui.Rect, y: float, height: float, direction: Direction) -> Tuple[int, int, bool]:
            resize_down_limit_reached = False

            if y + height > parent_rect.y + parent_rect.height and direction['down']:
                # print(f'_clip_down: down clipping')

                height = parent_rect.y + parent_rect.height - y

                resize_down_limit_reached = True

                if testing:
                    print(f'_clip_right: {resize_down_limit_reached=}')

            return round(y), round(height), resize_down_limit_reached

        def resize_pixels_relative(self, rect_cc: ui.Rect, rect_id: int, delta_width: float, delta_height: float, direction_in: Direction) -> Tuple[bool, bool, bool, bool, bool]:
            start_time = time.time_ns()

            result = resize_left_limit_reached = resize_up_limit_reached = resize_right_limit_reached = resize_down_limit_reached = False

            # start with the current values
            x = new_x = rect.x
            y = new_y = rect.y
            width = rect.width
            height = rect.height
            new_width = width + delta_width
            new_height = height + delta_height

            if testing:
                    print(f'resize_pixels_relative: starting {delta_width=}, {delta_height=}')

            # invert directions when shrinking non-uniformly. that is, we are shrinking *toward*
            #  the given direction rather than shrinking away from that direction.
            direction = direction_in.copy()
            if not all(direction.values()):
                if delta_width < 0:
                    temp = direction["right"]
                    direction["right"] = direction["left"]
                    direction["left"] = temp
                    # print(f'resize_pixels_relative: swapped left and right')
                #
                if delta_height < 0:
                    temp = direction["up"]
                    direction["up"] = direction["down"]
                    direction["down"] = temp
                    # print(f'resize_pixels_relative: swapped up and down')

            # are we moving diagonally?
            direction_count = sum(direction.values())

            if direction_count == 1:    # horizontal or vertical
                # print(f'resize_pixels_relative: single direction (horizontal or vertical)')
                # apply changes as indicated
                if direction["left"]:
                    new_x = new_x - delta_width
                    new_x, new_width, resize_left_limit_reached = self._clip_left(rect_cc, rect_id, new_x, new_width, direction)
                #
                if direction["up"]:
                    new_y = new_y - delta_height
                    new_y, new_height, resize_up_limit_reached = self._clip_up(rect_cc, rect_id, new_y, new_height, direction)
                #
                if direction["right"]:
                    new_x, new_width, resize_right_limit_reached = self._clip_right(rect_cc, rect_id, new_x, new_width, direction)
                #
                if direction["down"]:
                    new_height = new_height + delta_height
                    new_y, new_height, resize_down_limit_reached = self._clip_down(rect_cc, rect_id, new_y, new_height, direction)

            elif direction_count == 2:    # stretch diagonally
                if direction["left"] and direction["up"]:
                    # we are stretching northwest so the coordinates must not change for the southeastern corner
                    new_x = new_x - delta_width
                    new_y = new_y - delta_height

                    new_x, new_width, resize_left_limit_reached = self._clip_left(rect_cc, rect_id, new_x, new_width, direction)
                    new_y, new_height, resize_up_limit_reached = self._clip_up(rect_cc, rect_id, new_y, new_height, direction)

                    #print(f'resize_pixels_relative: left and up')

                elif direction["right"] and direction["up"]:
                    # we are stretching northeast so the coordinates must not change for the southwestern corner

                    # adjust y to account for the entire change in height
                    new_y = new_y - delta_height

                    new_x, new_width, resize_right_limit_reached = self._clip_right(rect_cc, rect_id, new_x, new_width, direction)
                    new_y, new_height, resize_up_limit_reached = self._clip_up(rect_cc, rect_id, new_y, new_height, direction)

                    #print(f'resize_pixels_relative: right and up')

                elif direction["right"] and direction["down"]:
                    # we are stretching southeast so the coordinates must not change for the northwestern corner,
                    # nothing to do here x and y are already set correctly for this case
                    new_x, new_width, resize_right_limit_reached = self._clip_right(rect_cc, rect_id, new_x, new_width, direction)
                    new_y, new_height, resize_down_limit_reached = self._clip_down(rect_cc, rect_id, new_y, new_height, direction)

                    #print(f'resize_pixels_relative: right and down')

                elif direction["left"] and direction["down"]:
                    # we are stretching southwest so the coordinates must not change for the northeastern corner,
                    # adjust x to account for the entire change in width
                    new_x = new_x - delta_width

                    new_x, new_width, resize_left_limit_reached = self._clip_left(rect_cc, rect_id, new_x, new_width, direction)
                    new_y, new_height, resize_down_limit_reached = self._clip_down(rect_cc, rect_id, new_y, new_height, direction)

                    #print(f'resize_pixels_relative: left and down')

            elif direction_count == 4:    # stretch from center
                if (delta_width == 0 or abs(delta_width) >= 2) and (delta_height == 0 or abs(delta_height) >= 2):
                    # normal case, delta values are divisible by two
                    new_x = new_x - delta_width / 2
                    new_y = new_y - delta_height / 2
                else:
                    if testing:
                        print(f'resize_pixels_relative: delta width and/or height are too small (<2), alternating size and position changes')

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

                if testing:
                    print(f'resize_pixels_relative: before left clip: {new_x=}, {new_width=}')
                new_x, new_width, resize_left_limit_reached = self._clip_left(rect_cc, rect_id, new_x, new_width, direction)
                if testing:
                    print(f'resize_pixels_relative: after left clip: {new_x=}, {new_width=}')

                new_y, new_height, resize_up_limit_reached = self._clip_up(rect_cc, rect_id, new_y, new_height, direction)

                if testing:
                    print(f'resize_pixels_relative: before right clip: {new_x=}, {new_width=}')
                new_x, new_width, resize_right_limit_reached = self._clip_right(rect_cc, rect_id, new_x, new_width, direction)
                if testing:
                    print(f'resize_pixels_relative: after right clip: {new_x=}, {new_width=}')

                new_y, new_height, resize_down_limit_reached = self._clip_down(rect_cc, rect_id, new_y, new_height, direction)

                #print(f'resize_pixels_relative: from center')

            # if testing:
            #     print(f'move_pixels_relative: {delta_x=}, {delta_y=}, {delta_width=}, {delta_height=}')

            if testing:
                print(f'resize_pixels_relative: {width=}, {new_width=}, {height=}, {new_height=}')

            new_values = (new_x, new_y, new_width, new_height)

            if testing:
                print(f'resize_pixels_relative: setting rect {new_values=}')

            result = False
            try:
                # make it so
                result = self.compass_control.set_rect(rect_cc, rect_id, ui.Rect(*new_values))
            except CompassControl.RectUpdateError as e:
                self.compass_control._handle_rect_update_error(e)

            if not result:
                # shrink is a special case, need to detect when the rectangle has shrunk to a minimum by
                # watching expected values to see when they stop changing as requested.
                if self.continuous_resize_width_increment < 0:
                    if rect.x != new_x or rect.width != new_width:
                        resize_left_limit_reached = True
                        resize_right_limit_reached = True
                        if testing:
                            print(f'resize_pixels_relative: horizontal shrink limit reached')

                if self.continuous_resize_height_increment < 0:
                    if rect.y != new_y or rect.height != new_height:
                        resize_up_limit_reached = True
                        resize_down_limit_reached = True
                        if testing:
                            print(f'resize_pixels_relative: vertical shrink limit reached')

            elapsed_time_ms = (time.time_ns() - start_time) / 1e6
            if testing:
                print(f'resize_pixels_relative: done ({elapsed_time_ms} ms)')

            return result, resize_left_limit_reached, resize_up_limit_reached, resize_right_limit_reached, resize_down_limit_reached

        def resize_absolute(self, rect_cc: ui.Rect, rect_id: int, target_width: float, target_height: float, region_in: Optional[Direction] = None) -> None:
            x = rect.x
            y = rect.y

            delta_width = target_width - rect.width
            delta_height = target_height - rect.height

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

                x, y = self.translate_top_left_by_region(rect_cc, rect_id, target_width, target_height, region)

                if testing:
                    print(f'resize_absolute: translated top left position: {x,y}')

            result = False
            try:
                result = self.compass_control.set_rect(rect_cc, rect_id, ui.Rect(round(x), round(y), round(target_width), round(target_height)))
            except CompassControl.RectUpdateError as e:
                self.compass_control._handle_rect_update_error(e)

            if testing:
                print(f'resize_absolute: {rect=}')
                ctrl.mouse_move(rect.x, rect.y)


    # CompassControl methods

    # Bresenham line code, from
    #       https://github.com/encukou/bresenham/blob/master/bresenham.py
    def bresenham(self, x0: int, y0: int, x1: int, y1: int) -> Tuple[int, int]:
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
            self.continuous_iteration = 0

    def revert(self, rect_cc: ui.Rect, rect_id: int) -> None:
        if self.last_rect and self.last_rect['id'] == rect_id:
            if testing:
                print(f'revert: reverting size and/or position for {self.last_rect}')

            result = False
            try:
                result = self.set_rect(rect_cc, rect_id, self.last_rect['rect'])
            except CompassControl.RectUpdateError as e:
                self._handle_rect_update_error(e)            

    def snap(self, rect_cc: ui.Rect, rect_id: int, parent_rect: ui.Rect, percent: int, direction: Direction) -> None:
        target_width = (parent_rect.width * (percent/100))
        target_height = (parent_rect.height * (percent/100))

        # move rectangle center to parent rectangle center
        self.move_absolute(rect_cc, rect_id, parent_rect.center.x, parent_rect.center.y, direction)

        # set rectangle size
        self.resize_absolute(rect_cc, rect_id, target_width, target_height, direction)

    def get_edge_midpoint(self, rect_cc: ui.Rect, direction: Direction) -> Tuple[float, float]:
        x = y = None

        direction_count = sum(direction.values())
        if direction_count == 1:
            if direction['left']: # west
                x = rect_cc.x
                y = (rect_cc.y + rect_cc.height) // 2
            elif direction['up']: # north
                x = (rect_cc.x + rect_cc.width) // 2
                y = rect_cc.y
            elif direction['right']: # east
                x = rect_cc.x + rect_cc.width
                y = (rect_cc.y + rect_cc.height) // 2
            elif direction['down']: # south
                x = (rect_cc.x + rect_cc.width) // 2
                y = rect_cc.y + rect_cc.height

        return x, y

    def get_corner(self, rect_cc: ui.Rect, direction: Direction) -> Tuple[float, float]:
        x = y = None

        direction_count = sum(direction.values())
        if direction_count == 2:
            if direction['left'] and direction['up']: # northwest
                x = rect_cc.x
                y = rect_cc.y
            elif direction['right'] and direction['up']: # northeast
                x = rect_cc.x + rect_cc.width
                y = rect_cc.y
            elif direction['right'] and direction['down']: # southeast
                x = rect_cc.x + rect_cc.width
                y = rect_cc.y + rect_cc.height
            elif direction['left'] and direction['down']: # southwest
                x = rect_cc.x
                y = rect_cc.y + rect_cc.height

        return x, y

    def get_center(self, rect_cc: ui.Rect) -> Tuple[float, float]:
        return rect_cc.center.x, rect_cc.center.y

    def get_target_point(self, rect_cc: ui.Rect, rect_id: int, parent_rect: ui.Rect, direction: Direction) -> Tuple[int, int]:
        target_x = target_y = None

        direction_count = sum(direction.values())
        if direction_count == 1:    # horizontal or vertical
            target_x, target_y = self.get_edge_midpoint(parent_rect, direction)
        elif direction_count == 2:    # diagonal
            target_x, target_y = self.get_corner(parent_rect, direction)
        elif direction_count == 4:    # center
            target_x, target_y = self.get_center(parent_rect)

        return round(target_x), round(target_y)

    def continuous_stop(self) -> None:
        with self.continuous_mutex:
            if not self.mover.continuous_move_job and not self.sizer.continuous_resize_job:
                if testing:
                    print('continuous_stop: no jobs to stop (may have stopped automatically via clipping logic)')
                return

            if testing:
                print(f'continuous_stop: current thread = {threading.get_native_id()}')

            if self.mover.continuous_move_job:
                cron.cancel(self.mover.continuous_move_job)

            if self.sizer.continuous_resize_job:
                cron.cancel(self.sizer.continuous_resize_job)

            # disable 'stop' command
            ctx.tags = []

            if self.continuous_old_rect:
                # remember starting rectangle
                if testing:
                    print(f'continuous_stop: {self.continuous_old_rect=}')

                self.last_rect = {
                    'id': rect_id,
                    'rect': self.continuous_old_rect
                }
                self.continuous_old_rect = None

            self._reset_continuous_flags()

            _stop_gui.hide()

    def get_diagonal_length(self, rect: ui.Rect) -> float:
        return math.sqrt(((rect.width - rect.x) ** 2) + ((rect.height - rect.y) ** 2))

    def get_center_to_center_rect(self, rect_cc: ui.Rect, rect_id: int, other_rect: ui.Rect) -> Tuple[ui.Rect, bool, bool]:
        width = rect.width
        height = rect.y

        rect_center = rect.center

        other_center = other_rect.center

        width = abs(rect_center.x - other_center.x)
        horizontal_multiplier = 1 if rect_center.x <= other_center.x else -1

        height = abs(rect_center.y - other_center.y)
        vertical_multiplier = 1 if rect_center.y <= other_center.y else -1

        center_to_center_rect = ui.Rect(round(other_center.x), round(rect_center.y), round(width), round(height))
        print(f'_get_center_to_center_rect: returning {center_to_center_rect=}, {horizontal_multiplier=}, {vertical_multiplier=}')

        return center_to_center_rect, horizontal_multiplier, vertical_multiplier

    def get_component_dimensions(self, rect_cc: ui.Rect, rect_id: int, parent_rect: ui.Rect, distance: float, direction: Direction, operation: str) -> Tuple[int, int]:
        delta_width = delta_height = 0
        rect = rect
        direction_count = sum(direction.values())
        if operation == 'move' and direction_count == 4:    # move to center
            # this is a special case - 'move center' - we return signed values for this case

            rect, horizontal_multiplier, vertical_multiplier = self.get_center_to_center_rect(w)
            diagonal_length = self.get_diagonal_length(rect)

            rect_center = rect.center

            parent_center = parent_rect.center

            # from https://math.stackexchange.com/questions/175896/finding-a-point-along-a-line-a-certain-distance-away-from-another-point
            ratio_of_differences = distance / diagonal_length
            new_x = (((1 - ratio_of_differences) * rect_center.x) + (ratio_of_differences * parent_center.x))
            new_y = (((1 - ratio_of_differences) * rect_center.y) + (ratio_of_differences * parent_center.y))

            if testing:
                print(f"_get_component_dimensions: {diagonal_length=}, {new_x=}, {new_y=}")

            delta_width = abs(new_x - rect_center.x) * horizontal_multiplier
            delta_height = abs(new_y - rect_center.y) * vertical_multiplier

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
            if direction_count == 1:    # horizontal or vertical
                if direction["left"] or direction["right"]:
                    delta_width = distance
                elif direction["up"] or direction["down"]:
                    delta_height = distance
            else:  # diagonal
                diagonal_length = self.get_diagonal_length(rect)
                ratio = distance / diagonal_length
                delta_width = rect.width * ratio
                delta_height = rect.height * ratio

        if testing:
            print(f"_get_component_dimensions: returning {delta_width}, {delta_height}")

        return round(delta_width), round(delta_height)

    def get_component_dimensions_by_percent(self, rect_cc: ui.Rect, rect_id: int, percent: float, direction: Direction, operation: str) -> Tuple[int, int]:
        if testing:
            print(f'_get_component_dimensions_by_percent: {percent=}')

        rect = rect
        direction_count = sum(direction.values())
        if operation == 'move' and direction_count == 4:    # move to center
            rect, *unused = self.get_center_to_center_rect(w)

        if direction_count  == 1:    # horizontal or vertical
            if direction["left"] or direction["right"]:
                distance = rect.width * (percent/100)
            elif direction["up"] or direction["down"]:
                distance = diagonal_length * (percent/100)
        else:  # diagonal
            diagonal_length = self.get_diagonal_length(rect)
            distance =  rect.height * (percent/100)

        return self.get_component_dimensions(rect_cc, rect_id, distance, direction, operation)

    def _get_continuous_parameters(self, rect_cc: ui.Rect, rect_id: int, parent_rect: ui.Rect, rate_cps: float, dpi_x: float, dpi_y: float, direction: Direction, operation: str, frequency: str) -> Tuple[int, int]:
        if testing:
            print(f'get_continuous_parameters: {rate_cps=}')

        # convert rate from centimeters to inches, to match dpi units
        rate_ips = rate_cps / 2.54

        # calculate dots per millisecond
        dpms_x = (rate_ips * dpi_x) / 1000
        dpms_y = (rate_ips * dpi_y) / 1000

        if testing:
            print(f'get_continuous_parameters: {dpms_x=}, {dpms_y=}')

        width_increment = height_increment = 0

        direction_count = sum(direction.values())
        if direction_count == 1:
            # single direction
            if direction["left"] or direction["right"]:
                width_increment = dpms_x *  self.frequency
            elif direction["up"] or direction["down"]:
                height_increment = dpms_y *  self.frequency
        else:    # diagonal
            width_increment = dpms_x *  self.frequency
            height_increment = dpms_y *  self.frequency

            if direction_count == 4 and operation == 'move':    # move to center
                if testing:
                    print(f"get_continuous_parameters: 'move center' special case")

                # special case, return signed values
                if rect.center.x > parent_rect.center.x:
                    width_increment *= -1
                #
                if rect.center.y > parent_rect.center.y:
                    height_increment *= -1

        if testing:
            print(f"get_continuous_parameters: returning {width_increment=}, {height_increment=}")

        return round(width_increment), round(height_increment)

    def set_rect(self, old_rect: ui.Rect, rect_id: int, rect_in: ui.Rect) -> bool:
        # raise Exception('set_rect() must be implemented in context')
        set_method = self.set_method
        result = set_method(old_rect, rect_id, rect_in)
        
        # remember old rectangle, for 'revert'
        self.last_window = {
            'id': id,
            'rect': old_rect
        }        

        return result

# # globals
# compass_control = CompassControl()            

## talon stuff

mod = Module()

# mod.tag(compass_control.continuous_tag_name, desc="Enable stop command during continuous rectangle move/resize.")

# # context used to enable/disable the tag for controlling whether the 'stop' command is active
# ctx = Context()

# # context containing the stop command, enabled only when a continuous move/resize is running
# ctx_stop = Context()
# ctx_stop.matches = fr"""
# tag: user.{compass_control.continuous_tag_name}
# """


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

# @mod.action_class
# class Actions:
#     def compass_control_show() -> None:
#         "Shows information about current rectangle position and size"
#         raise Exception('show action must be implemented in context')

#     def compass_control_hide() -> None:
#         "Hides the rectangle information window"
#         raise Exception('show action must be implemented in context')

#     def compass_control_stop() -> None:
#         "Module action declaration for stopping current rectangle move/resize operation"
#         if testing:
#             print('stop action not implemented in current context')
#         pass

#     def compass_control_move(rect_cc: ui.Rect, rect_id: int, direction: Optional[Direction] = None) -> None:
#         "Move rectangle in small increments in the given direction, until stopped"
#         compass_control.mover.init_continuous(rect_cc, rect_id, direction)

#     def compass_control_move_absolute(rect_cc: ui.Rect, rect_id: int, x_in: float, y_in: float, region: Optional[Direction] = None) -> None:
#         "Move rectangle to given absolute position, centered on the point indicated by the given region"

#         x = x_in
#         y = y_in

#         compass_control.mover.move_absolute(rect_cc, rect_id, x, y, region)

#     def compass_control_stretch(rect_cc: ui.Rect, rect_id: int, direction: Optional[Direction] = None) -> None:
#         "Stretch rectangle in small increments until stopped, optionally in the given direction"

#         if not direction:
#             direction = compass_direction(['center'])

#         compass_control.sizer.init_continuous(rect_cc, rect_id, 1, direction)

#     def compass_control_shrink(rect_cc: ui.Rect, rect_id: int, direction: Optional[Direction] = None) -> None:
#         "Shrink rectangle in small increments until stopped, optionally in the given direction"

#         if not direction:
#             direction = compass_direction(['center'])

#         compass_control.sizer.init_continuous(rect_cc, rect_id, -1, direction)

#     def compass_control_resize_absolute(rect_cc: ui.Rect, rect_id: int, target_width: float, target_height: float, region: Optional[Direction] = None) -> None:
#         "Size rectangle to given absolute dimensions, optionally by stretching/shrinking in the direction indicated by the given region"

#         compass_control.sizer.resize_absolute(rect_cc, rect_id, target_width, target_height, region)

#     def compass_control_move_pixels(rect_cc: ui.Rect, rect_id: int, distance: int, direction: Direction) -> None:
#         "move rectangle some number of pixels"

#         delta_width, delta_height = compass_control.get_component_dimensions(rect_cc, rect_id, distance, direction, 'move')

#         return compass_control.mover.move_pixels_relative(rect_cc, rect_id, delta_width, delta_height, direction)

#     def compass_control_move_percent(rect_cc: ui.Rect, rect_id: int, percent: float, direction: Direction) -> None:
#         "move rectangle some percentage of the current size"

#         delta_width, delta_height = compass_control.get_component_dimensions_by_percent(rect_cc, rect_id, percent, direction, 'move')

#         return compass_control.mover.move_pixels_relative(rect_cc, rect_id, delta_width, delta_height, direction)

#     def compass_control_resize_pixels(rect_cc: ui.Rect, rect_id: int, distance: int, direction: Direction) -> None:
#         "change rectangle size by pixels"

#         delta_width, delta_height = compass_control.get_component_dimensions(rect_cc, rect_id, distance, direction, 'resize')

#         if testing:
#             print(f'resize_pixels: {delta_width=}, {delta_height=}')

#         compass_control.sizer.resize_pixels_relative(rect_cc, rect_id, delta_width, delta_height, direction)

#     def compass_control_resize_percent(rect_cc: ui.Rect, rect_id: int, percent: float, direction: Direction) -> None:
#         "change rectangle size by a percentage of current size"

#         delta_width, delta_height = compass_control.get_component_dimensions_by_percent(rect_cc, rect_id, percent, direction, 'resize')

#         if testing:
#             print(f'resize_percent: {delta_width=}, {delta_height=}')

#         compass_control.sizer.resize_pixels_relative(rect_cc, rect_id, delta_width, delta_height, direction)

#     def compass_control_snap_percent(rect_cc: ui.Rect, rect_id: int, percent: int) -> None:
#         "center rectangle and change size to given percentage of parent rectangle (in each direction)"

#         direction = compass_direction(['center'])

#         compass_control.snap(rect_cc, rect_id, percent, direction)

#     def compass_control_revert(rect_cc: ui.Rect, rect_id: int) -> None:
#         "restore current rectangle's last remembered size and position"

#         compass_control.revert(w)
    
#     def compass_control_test_bresenham(num: int) -> None:
#         "test modified bresenham algo"

#         if num == 1:
#             compass_control.mover.test_bresenham_1()

# @ctx_stop.action_class("user")
# class RectangleActions:
#     """
#     # Commands for controlling continuous rectangle move/resize operations
#     """
#     def stop() -> None:
#         "Stops current rectangle move/resize operation"
#         compass_control.stop()