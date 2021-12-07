# """
# Tools for managing the size and position of rectangles using cardinal and ordinal directions, e.g. North, Southwest, etc.

# Continuous move/resize machinery adapted from mouse.py.
# """

# WIP - populate docstrings
# WIP - reorder methods

# WIP - need help with 'win shrink' automatic stop mechanism - resize_history approach fails because
# WIP - calls to set_rect() time out when the window hits the minimum in one dimension, whereas the
# WIP - change checking approach fails because changes will partially fail before the window has
# WIP - reached its minimum size.

# WIP - 'win snap 200 percent' moves rectangle up a bit, turns out talon resize() API will not increase
# WIP - height beyond 1625 for some reason...perhaps related to the size of the largest of my 3 screens,
# WIP - which is height 1600.

# WIP - on linux, continuous stretch limits don't work properly because the visible rect size is the same
# WIP - as the physical rect size even though they are not really the same.


from typing import Any, Callable, Dict, List, Tuple, Optional, Iterator

import math
import logging
import threading
import time

from talon import ui, Module, ctrl, cron, Context
from talon.types.point import Point2d

# a type for representing compass directions
Direction = Dict[str, bool]

# turn debug messages on and off
testing: bool = True

class CompassControl:

    def __init__(self, continuous_tag_name: str, set_method: Callable, stop_method: Callable, move_frequency: str, resize_frequency: str, move_rate: float, resize_rate: float, verbose_warnings: int):

        # the method to call to actually set the new size and position of the given rectangle
        self.set_method = set_method
        
        self.verbose_warnings: int = verbose_warnings

        # remember the last rectangle so we can always revert back to it later
        self.last_rect: Dict = dict()

        # tag used to enable/disable commands used to manage continuous move/resize operations, e.g. 'stop'
        self.continuous_tag_name: str = continuous_tag_name
        self.continuous_tag_name_qualified: str = 'user.' + self.continuous_tag_name
        
        # the method to call when stopping a continuous move/resize operation, so the caller can do any additional tasks, as required
        self.continuous_stop_method = stop_method

        self.continuous_mutex: threading.RLock = threading.RLock()

        # variables for managing continuous move/resize operations
        self.continuous_iteration: int = 0
        self.continuous_direction: Direction = None
        self.continuous_old_rect: ui.Rect = None
        self.continuous_rect: ui.Rect = None
        self.continuous_rect_id: int = None
        self.continuous_parent_rect: ui.Rect = None

        # print(f'CompassControl.__init__: {move_rate=}')

        # the control uses a mover instance and a sizer instance
        self.mover: CompassControl.Mover = CompassControl.Mover(self, move_frequency, move_rate)
        self.sizer: CompassControl.Sizer = CompassControl.Sizer(self, resize_frequency, resize_rate)

    # error thrown when a mover resize request is not completely successful
    class RectUpdateError(Exception):
        def __init__(self, rect_id, initial,  requested, actual):
            # along with error reporting, these values are used to update last_rect in support of revert functionality
            self.rect_id = rect_id
            self.initial = initial
            self.requested = requested
            self.actual = actual
        
    def _handle_rect_update_error(self, e: RectUpdateError) -> None:
        if self.verbose_warnings:
            position_matches_request = (e.requested.x, e.requested.y) == (e.actual.x, e.actual.y)
            size_matches_request = (e.requested.width, e.requested.height) == (e.actual.width, e.actual.height)

            if not position_matches_request:
                logging.warning(f'after update, rectangle position does not exactly match request: {e.requested.x, e.requested.y} -> {e.actual.x, e.actual.y}')
        
            if not size_matches_request:
                logging.warning(f'after update, rectangle size does not exactly match request: {e.requested.width, e.requested.height} -> {e.actual.width, e.actual.height}')

        self.save_last_rect(e.rect_id, e.initial)
        
    class Mover:
        def __init__(self, compass_control, frequency: str, rate: float):
            # ref to parent
            self.compass_control: CompassControl = compass_control

            # settings for managing continuous move/resize operations
            self.continuous_frequency_str: str = frequency
            self.continuous_frequency: float = float((frequency)[:-2])
            self.continuous_rate: float = rate

            # variables used during continuous move/resize operations
            self.continuous_width_increment: int = 0
            self.continuous_height_increment: int = 0
            self.continuous_job: Any = None

            # bresenham generator used for 'move to center' operations
            self.continuous_bres: Iterator[(int, int)] = None

            # if testing:
            #     print(f'Mover.__init__: {rate=}')

        # reset variables used during continuous operations
        def _reset_continuous(self) -> None:
            with self.compass_control.continuous_mutex:
                self.continuous_width_increment = 0
                self.continuous_height_increment = 0
                self.continuous_job = None
                self.continuous_bres = None

        # this is the engine that handles each continuous iteration
        def continuous_helper(self) -> None:
            def _move_it(rect: ui.Rect, rect_id: int, parent_rect: ui.Rect, delta_x: float, delta_y: float, direction: Direction) -> Tuple[bool, ui.Rect]:
                result, rect, horizontal_limit_reached, vertical_limit_reached = self.move_pixels_relative(rect, rect_id, parent_rect, delta_x, delta_y, self.compass_control.continuous_direction)
                if not result:
                    if testing:
                        print(f'continuous_helper: rectangle move failed. {result=}, {rect=}, {horizontal_limit_reached=}, {vertical_limit_reached=}')
                    self.compass_control.continuous_stop()
                elif (horizontal_limit_reached and vertical_limit_reached):
                    if testing:
                        print(f'continuous_helper: rectangle move is complete. {result=}, {rect=}, {horizontal_limit_reached=}, {vertical_limit_reached=}')
                    self.compass_control.continuous_stop()
                    result = None
                else:
                    if horizontal_limit_reached:
                        self.continuous_width_increment = 0

                    if vertical_limit_reached:
                        self.continuous_height_increment = 0

                return result, rect

            start_mutex_wait = time.time_ns()

            with self.compass_control.continuous_mutex:
                iteration = self.compass_control.continuous_iteration

                elapsed_time_ms = (time.time_ns() - start_mutex_wait) / 1e6
                if testing:
                    print(f'continuous_helper: iteration {iteration} mutex wait ({elapsed_time_ms} ms)')

                start_time = time.time_ns()

                # if testing:
                #     print(f'continuous_helper: current thread = {threading.get_native_id()}')

                if not self.continuous_job:
                    # seems sometimes this gets called while the job is being canceled, so just return in that case
                    return

                rect = self.compass_control.continuous_rect
                rect_id = self.compass_control.continuous_rect_id
                parent_rect = self.compass_control.continuous_parent_rect

                if testing:
                    print(f'continuous_helper: starting iteration {iteration} - {rect=}')

                if self.continuous_width_increment or self.continuous_height_increment:
                    direction_count = sum(self.compass_control.continuous_direction.values())
                    if direction_count != 4:
                        result, rect = _move_it(rect, rect_id, parent_rect, self.continuous_width_increment, self.continuous_height_increment, self.compass_control.continuous_direction)
                        self.compass_control.continuous_rect = rect
                        if not result:
                            if testing:
                                print(f'continuous_helper: move failed')
                    else:    # move to center (special case)
                        initial_x = rect.x
                        initial_y = rect.y
                        cumulative_delta_x = cumulative_delta_y = 0
                        center_x = center_y = 0
                        while True:
                            if testing:
                                print(f'continuous_helper: current rectangle top left = {rect.x, rect.y}')

                            (x, y) = (round(rect.x), round(rect.y))
                            try:
                                # skip until we see some movement
                                while (x, y) == (round(rect.x), round(rect.y)):
                                    center_x, center_y = next(self.continuous_bres)
                                    # translate center coordinates to top left
                                    x, y = self.translate_top_left_by_region(rect, rect_id, center_x, center_y, self.compass_control.continuous_direction)
                                    if testing:
                                        print(f'continuous_helper: next bresenham point = {center_x, center_y}, corresponding to top left = {x, y}')
                            except StopIteration:
                                if testing:
                                    print(f'continuous_helper: StopIteration')

                                self.compass_control.continuous_stop()
                                
                                # return
                                break

                            delta_x = abs(x - rect.x)
                            if self.continuous_width_increment < 0:
                                delta_x *= -1

                            delta_y = abs(y - rect.y)
                            if self.continuous_height_increment < 0:
                                delta_y *= -1

                            if testing:
                                print(f'continuous_helper: stepping from {rect.x, rect.y} to {x, y}, {delta_x=}, {delta_y=}')

                            print(f'continuous_helper: before move {rect=}')
                            result, rect = _move_it(rect, rect_id, parent_rect, delta_x, delta_y, self.compass_control.continuous_direction)
                            self.compass_control.continuous_rect = rect
                            if not rect:
                                if testing:
                                    print(f'continuous_helper: move failed')
                                return
                            print(f'continuous_helper: after move {rect=}')

                            cumulative_delta_x = abs(rect.x - initial_x)
                            if testing:
                                print(f'continuous_helper: {cumulative_delta_x=}, {self.continuous_width_increment=}')
                            if self.continuous_width_increment != 0 and cumulative_delta_x >= abs(self.continuous_width_increment):
                                if testing:
                                    print(f'continuous_helper: reached horizontal limit for current iteration, stopping')
                                break

                            cumulative_delta_y = abs(rect.y - initial_y)
                            if testing:
                                print(f'continuous_helper: {cumulative_delta_y=}, {self.continuous_height_increment=}')
                            if self.continuous_height_increment != 0 and cumulative_delta_y >= abs(self.continuous_height_increment):
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
                if elapsed_time_ms > self.continuous_frequency:
                    if self.compass_control.verbose_warnings != 0:
                        logging.warning(f'continuous_helper: move iteration {iteration} took {elapsed_time_ms}ms, longer than the current move_frequency setting. actual rate may not match the continuous_rate setting.')

                self.compass_control.continuous_iteration += 1
            
        # commence continuous operation
        def _start_continuous(self) -> None:
            with self.compass_control.continuous_mutex:
                ctx.tags = [self.compass_control.continuous_tag_name_qualified]
                self.continuous_job = cron.interval(self.continuous_frequency_str, self.continuous_helper)
                if testing:
                    print(f'_start_continuous: {self.continuous_job=}')

        # initialize continuous operation
        def init_continuous(self, rect: ui.Rect, rect_id: int, parent_rect: ui.Rect, dpi_x: float, dpi_y: float, direction: Direction) -> None:
            with self.compass_control.continuous_mutex:
                if self.continuous_job:
                    if testing:
                        print(f'init_continuous: {self.continuous_job=}')
                    logging.warning('cannot start a move job when one is already running')
                    return

                self.compass_control._reset_continuous_flags()

                self.compass_control.continuous_old_rect = rect
                self.compass_control.continuous_rect = rect
                self.compass_control.continuous_rect_id = rect_id
                self.compass_control.continuous_parent_rect = parent_rect
                self.compass_control.continuous_direction = direction
                
                print(f'init_continuous: {self.continuous_frequency_str=}')
                self.continuous_width_increment, self.continuous_height_increment = self.compass_control._get_continuous_parameters(
                                    rect, rect_id, parent_rect, self.continuous_rate, dpi_x, dpi_y, direction, 'move', self.continuous_frequency)

                if testing:
                    print(f'init_continuous: {self.continuous_width_increment=}, {self.continuous_height_increment=}')

                direction_count = sum(self.compass_control.continuous_direction.values())
                if direction_count == 4:    # move to center (special case)
                    # follow path from rectangle center to parent rectangle center
                    x0 = round(rect.center.x)
                    y0 = round(rect.center.y)

                    x1, y1 = self.compass_control.get_target_point(rect, rect_id, parent_rect, direction)

                    # note that this is based on the line from rectangle center to parent rectangle center, resulting
                    # coordinates will have to be translated to top left to set rectangle position, etc.
                    self.continuous_bres = self.compass_control.bresenham(x0, y0, x1, y1)

                    # discard initial point (we're already there)
                    first = next(self.continuous_bres)

                self._start_continuous()

        # adjust rectangle coordinates to keep it from overlapping the limits of the screen
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

        # move rectangle in given direction as indicated by the given delta values
        def move_pixels_relative(self, rect: ui.Rect, rect_id: int, parent_rect: ui.Rect, delta_x: float, delta_y: float, direction: Direction) -> Tuple[ui.Rect, bool, bool]:
            start_time = time.time_ns()

            result = None
            horizontal_limit_reached = vertical_limit_reached = False

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

                new_x, new_y, horizontal_limit_reached, vertical_limit_reached = self._clip_to_fit(rect, rect_id, parent_rect, x, y, rect.width, rect.height, direction)
            else:    # move to center
                rect_width = rect.width
                rect_height = rect.height

                new_x = x + delta_x
                new_y = y + delta_y

                new_rect_center = Point2d(round(new_x + rect_width/2), round(new_y + rect_height/2))

                target_x = parent_rect.center.x - rect_width/2
                target_y = parent_rect.center.y - rect_height/2

                # calculate distance between rectangle center and parent center
                distance_x = parent_rect.center.x - rect.center.x
                distance_y = parent_rect.center.y - rect.center.y

                if testing:
                    print(f'move_pixels_relative: {new_x=}, {new_y=}, {parent_rect.center.x=}, {parent_rect.center.y=}')
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

            try:
                # make it so
                result, rect = self.compass_control.set_rect(rect, rect_id, ui.Rect(new_x, new_y, rect.width, rect.height))
            except CompassControl.RectUpdateError as e:
                self.compass_control._handle_rect_update_error(e)

            elapsed_time_ms = (time.time_ns() - start_time) / 1e6
            if testing:
                print(f'move_pixels_relative: done {result=} ({elapsed_time_ms} ms)')

            return result, rect, horizontal_limit_reached, vertical_limit_reached

        # move rectangle in given direction to match the given values
        # note: this method is used by move_absolute(), which interprets the Direction argument
        # differently than elsewhere in this module.
        def translate_top_left_by_region(self, rect: ui.Rect, rect_id: int, target_x: float, target_y: float, region_in: Direction) -> Tuple[int, int]:

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

        # move rectangle in given direction to match the given values
        def move_absolute(self, rect_cc: ui.Rect, rect_id: int, x: float, y: float, region_in: Optional[Direction] = None) -> Tuple[bool, ui.Rect]:
            # find the point which we will move to the given coordinates, as indicated by the region.
            if region_in:
                x, y = self.translate_top_left_by_region(rect_cc, rect_id, x, y, region_in)

                if testing:
                    print(f'move_absolute: translated top left position: {x,y}')

            result = False
            try:
                result, rect = self.compass_control.set_rect(rect_cc, rect_id, ui.Rect(round(x), round(y), round(rect_cc.width), round(rect_cc.height)))
            except CompassControl.RectUpdateError as e:
                self.compass_control._handle_rect_update_error(e)

            if testing:
                print(f'move_absolute: {rect_cc=}')
                ctrl.mouse_move(x, y)

            return result, rect

        # test code
        def test_bresenham(self):
            x0 = 0
            y0 = 0
            x1 = 100
            y1 = 4
            max_width = 4
            max_height = 4

            bres = self.bresenham(x0, y0, x1, y1)
            try:
                while True:
                    b0 = next(bres)
                    print(f'test_bresenham_1: bresenham: {b0}')
            except StopIteration:
                print(f'test_bresenham_1: bresenham done')

    class Sizer:
        def __init__(self, compass_control, frequency: str, rate: str):
            self.compass_control: CompassControl = compass_control
            
            # settings for managing continuous move/resize operations            
            self.continuous_frequency_str: str = frequency
            self.continuous_frequency: float = float((frequency)[:-2])
            self.continuous_rate: float = rate

            # variables used during continuous move/resize operations
            self.continuous_width_increment: int = 0
            self.continuous_height_increment: int = 0
            self.continuous_job: Any = None
            self.continuous_alternation: str = None

            # keep rect history for use in detecting when the window stops shrinking during resize,
            # i.e. the minimum size has been reached and the resize operation should stop.
            self.continuous_resize_history: List = []

            # only one of these should be true at any time
            self.use_resize_history_for_shrink: bool = False
            self.use_change_check_for_shrink: bool = not self.use_resize_history_for_shrink

        # reset variables used during continuous operations
        def _reset_continuous(self) -> None:
            with self.compass_control.continuous_mutex:
                self.continuous_width_increment = 0
                self.continuous_height_increment = 0
                self.continuous_job = None
                self.continuous_alternation: str = None
                self.continuous_resize_history = []

        # this is the engine that handles each continuous iteration
        def continuous_helper(self) -> None:
            start_mutex_wait = time.time_ns()

            with self.compass_control.continuous_mutex:
                iteration = self.compass_control.continuous_iteration

                elapsed_time_ms = (time.time_ns() - start_mutex_wait) / 1e6
                if testing:
                    print(f'continuous_helper: mutex wait ({elapsed_time_ms} ms)')

                start_time = time.time_ns()

                if not self.continuous_job:
                    # seems sometimes this gets called while the job is being canceled, so just return in that case
                    return

                # retrieve rectangle from previous iteration
                rect = self.compass_control.continuous_rect
                rect_id = self.compass_control.continuous_rect_id
                parent_rect = self.compass_control.continuous_parent_rect

                if testing:
                    print(f'continuous_helper: starting iteration {iteration} - {rect=}')

                if not self.continuous_width_increment and not self.continuous_height_increment:
                    # if there's no work to do...
                    if testing:
                        print(f'continuous_helper: rectangle resize failed. {rect=}')
                    self.compass_control.continuous_stop()                 
                else:
                    # do the resize
                    result, rect, resize_left_limit_reached, resize_up_limit_reached, resize_right_limit_reached, resize_down_limit_reached = self.resize_pixels_relative(rect, rect_id, parent_rect, self.continuous_width_increment, self.continuous_height_increment, self.compass_control.continuous_direction)

                    # save updated rectangle for next iteration
                    self.compass_control.continuous_rect = rect

                    if result:
                        # the update succeeded, now need to check limits 
                        direction_count = sum(self.compass_control.continuous_direction.values())
                        if direction_count == 1:    # horizontal or vertical
                            if any([resize_left_limit_reached, resize_up_limit_reached, resize_right_limit_reached, resize_down_limit_reached]):
                                if testing:
                                    print(f'continuous_helper: single direction limit reached')
                                self.continuous_width_increment = 0
                                self.continuous_height_increment = 0
                        elif direction_count == 2:    # diagonal
                            if resize_left_limit_reached or resize_right_limit_reached:
                                if testing:
                                    print(f'continuous_helper: horizontal limit reached')
                                self.continuous_width_increment = 0
                            #
                            if resize_up_limit_reached or resize_down_limit_reached:
                                if testing:
                                    print(f'continuous_helper: vertical limit reached')
                                self.continuous_height_increment = 0
                        elif direction_count == 4:    # from center
                            if resize_left_limit_reached and resize_right_limit_reached:
                                if testing:
                                    print(f'continuous_helper: horizontal limit reached')
                                self.continuous_width_increment = 0

                            if resize_up_limit_reached and resize_down_limit_reached:
                                if testing:
                                    print(f'continuous_helper: vertical limit reached')
                                self.continuous_height_increment = 0
                    else: # resize was not completely successful
                        if rect and self.use_resize_history_for_shrink:
                            # shrink is a special case, need to detect when the rectangle has shrunk to a minimum by
                            # watching expected values to see when they stop changing as requested.
                            if self.continuous_width_increment < 0 and self.continuous_height_increment < 0:
                                # check resize history
                                value = (rect.width, rect.height)
                                if len(self.continuous_resize_history) == 2:
                                    if value == self.continuous_resize_history[0] == self.continuous_resize_history[1]:
                                        # window size has stopped changing...so quit trying
                                        if testing:
                                            print('_win_resize_continuous_helper: window size has stopped changing, quitting...')
                                        self.compass_control.continuous_stop()
                                    else:
                                        # chuck old data to make room for new data
                                        self.continuous_resize_history.pop(0)
                                #
                                # update history
                                self.continuous_resize_history.append(value)   
                        else:
                            if testing:
                                print(f'continuous_helper: rectangle resize failed. {rect=}')
                            self.compass_control.continuous_stop()                 

            elapsed_time_ms = (time.time_ns() - start_time) / 1e6
            if testing:
                print(f'continuous_helper: iteration {iteration} done ({elapsed_time_ms} ms)')
            if elapsed_time_ms > self.continuous_frequency:
                if self.compass_control.verbose_warnings != 0:
                    logging.warning(f'continuous_helper: resize iteration {iteration} took {elapsed_time_ms}ms, longer than the current resize_frequency setting. actual rate may not match the current rate setting.')

            # for testing
            one_loop_only = False
            if one_loop_only:
                self.compass_control.continuous_stop()
                return

            self.compass_control.continuous_iteration += 1

        # commence continuous operation
        def _start_continuous(self) -> None:
            with self.compass_control.continuous_mutex:
                # enable tag to enable the 'stop' command
                ctx.tags = [self.compass_control.continuous_tag_name_qualified]

                # start the job
                self.continuous_job = cron.interval(self.continuous_frequency_str, self.continuous_helper)

        # initialize continuous operation
        def init_continuous(self, rect: ui.Rect, rect_id: int, parent_rect: ui.Rect, multiplier: int, dpi_x: float, dpi_y: float, direction: Optional[Direction] = None) -> None:
            with self.compass_control.continuous_mutex:
                if self.continuous_job:
                    logging.warning('cannot start a resize job when one is already running')
                    return

                # get vertical and horizontal step sizes, to match the rate and frequency settings
                self.continuous_width_increment, self.continuous_height_increment = self.compass_control._get_continuous_parameters(
                                    rect, rect_id, parent_rect, self.continuous_rate, dpi_x, dpi_y, direction, '_resize', self.continuous_frequency)

                # apply multiplier to control whether we're stretching or shrinking
                self.continuous_width_increment *= multiplier
                self.continuous_height_increment *= multiplier

                # initialize
                self.compass_control.continuous_old_rect = rect
                self.compass_control.continuous_rect = rect
                self.compass_control.continuous_rect_id = rect_id
                self.compass_control.continuous_parent_rect = parent_rect
                self.compass_control.continuous_direction = direction

                if testing:
                    print(f'init_continuous: starting resize - {self.continuous_width_increment=}, {self.continuous_height_increment=}, {self.compass_control.continuous_direction=}, {multiplier=}')

                # let it roll
                self._start_continuous()

        # this could figures out what the top left coordinates should be for resizing in the given direction
        def translate_top_left_by_region(self, rect: ui.Rect, rect_id: int, target_width: float, target_height: float, direction: Direction) -> Tuple[int, int]:

            x = rect.x
            y = rect.y

            delta_width = target_width - rect.width
            delta_height = target_height - rect.height

            if self.compass_control.verbose_warnings != 0:
                if abs(delta_width) < 2:
                    logging.warning(f'_translate_top_left_by_region: width change is less than 2, which is too small for normal resize calculations, ymmv: {delta_width=}')
                if abs(delta_height) < 2:
                    logging.warning(f'_translate_top_left_by_region: height change is less than 2, which is too small for normal resize calculations, ymmv: {delta_height=}')

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
                # resize in all directions
                x = x - delta_width / 2
                y = y - delta_height / 2

            if testing:
                print(f"_translate_top_left_by_region: translated position: {x=}, {y=}, {target_width=}, {target_height=}")

            return round(x), round(y)

        # adjust rectangle coordinates to keep it from overlapping the left limit of the screen
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

        # adjust rectangle coordinates to keep it from overlapping the upper limit of the screen
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

        # adjust rectangle coordinates to keep it from overlapping the right limit of the screen
        def _clip_right(self, rect_cc: ui.Rect, rect_id: int, parent_rect: ui.Rect, x: float, width: float, direction: Direction) -> Tuple[int, int, bool]:
            resize_right_limit_reached = False

            if x + width > parent_rect.x + parent_rect.width and direction['right']:
                # print(f'_clip_right: right clipping')

                width = parent_rect.x + parent_rect.width - x

                if testing:
                    print(f'_clip_right: {resize_right_limit_reached=}')

                resize_right_limit_reached = True

            return round(x), round(width), resize_right_limit_reached

        # adjust rectangle coordinates to keep it from overlapping the lower limit of the screen
        def _clip_down(self, rect_cc: ui.Rect, rect_id: int, parent_rect: ui.Rect, y: float, height: float, direction: Direction) -> Tuple[int, int, bool]:
            resize_down_limit_reached = False

            if y + height > parent_rect.y + parent_rect.height and direction['down']:
                # print(f'_clip_down: down clipping')

                height = parent_rect.y + parent_rect.height - y

                resize_down_limit_reached = True

                if testing:
                    print(f'_clip_right: {resize_down_limit_reached=}')

            return round(y), round(height), resize_down_limit_reached

        # change size in given direction as indicated by the given delta values
        def resize_pixels_relative(self, rect: ui.Rect, rect_id: int, parent_rect: ui.Rect, delta_width: float, delta_height: float, direction_in: Direction) -> Tuple[bool, ui.Rect, bool, bool, bool, bool]:
            start_time = time.time_ns()

            result = resize_left_limit_reached = resize_up_limit_reached = resize_right_limit_reached = resize_down_limit_reached = False

            # start with the current values
            new_x = rect.x
            new_y = rect.y
            width = rect.width
            height = rect.height
            new_width = width + delta_width
            new_height = height + delta_height

            if testing:
                print(f'resize_pixels_relative: starting {rect=}, {delta_width=}, {delta_height=}, {new_width=}, {new_height=}')

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
                    new_x, new_width, resize_left_limit_reached = self._clip_left(rect, rect_id, parent_rect, new_x, new_width, direction)
                #
                if direction["up"]:
                    new_y = new_y - delta_height
                    new_y, new_height, resize_up_limit_reached = self._clip_up(rect, rect_id, parent_rect, new_y, new_height, direction)
                #
                if direction["right"]:
                    new_x, new_width, resize_right_limit_reached = self._clip_right(rect, rect_id, parent_rect, new_x, new_width, direction)
                #
                if direction["down"]:
                    new_y, new_height, resize_down_limit_reached = self._clip_down(rect, rect_id, parent_rect, new_y, new_height, direction)

            elif direction_count == 2:    # stretch diagonally
                if direction["left"] and direction["up"]:
                    # we are stretching northwest so the coordinates must not change for the southeastern corner
                    new_x = new_x - delta_width
                    new_y = new_y - delta_height

                    new_x, new_width, resize_left_limit_reached = self._clip_left(rect, rect_id, parent_rect, new_x, new_width, direction)
                    new_y, new_height, resize_up_limit_reached = self._clip_up(rect, rect_id, parent_rect, new_y, new_height, direction)

                    #print(f'resize_pixels_relative: left and up')

                elif direction["right"] and direction["up"]:
                    # we are stretching northeast so the coordinates must not change for the southwestern corner

                    # adjust y to account for the entire change in height
                    new_y = new_y - delta_height

                    new_x, new_width, resize_right_limit_reached = self._clip_right(rect, rect_id, parent_rect, new_x, new_width, direction)
                    new_y, new_height, resize_up_limit_reached = self._clip_up(rect, rect_id, parent_rect, new_y, new_height, direction)

                    #print(f'resize_pixels_relative: right and up')

                elif direction["right"] and direction["down"]:
                    # we are stretching southeast so the coordinates must not change for the northwestern corner,
                    # nothing to do here x and y are already set correctly for this case
                    new_x, new_width, resize_right_limit_reached = self._clip_right(rect, rect_id, parent_rect, new_x, new_width, direction)
                    new_y, new_height, resize_down_limit_reached = self._clip_down(rect, rect_id, parent_rect, new_y, new_height, direction)

                    #print(f'resize_pixels_relative: right and down')

                elif direction["left"] and direction["down"]:
                    # we are stretching southwest so the coordinates must not change for the northeastern corner,
                    # adjust x to account for the entire change in width
                    new_x = new_x - delta_width

                    new_x, new_width, resize_left_limit_reached = self._clip_left(rect, rect_id, parent_rect, new_x, new_width, direction)
                    new_y, new_height, resize_down_limit_reached = self._clip_down(rect, rect_id, parent_rect, new_y, new_height, direction)

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
                    if self.continuous_alternation == 'size':
                        # change position this time
                        new_x = new_x - delta_width
                        new_y = new_y - delta_height

                        # remove delta from the size values
                        new_width = width
                        new_height = height

                        self.continuous_alternation = 'position'
                    else:
                        # change size this time...nothing to actually do other than flip the toggle
                        self.continuous_alternation = 'size'

                if testing:
                    print(f'resize_pixels_relative: before left clip: {new_x=}, {new_width=}')
                new_x, new_width, resize_left_limit_reached = self._clip_left(rect, rect_id, parent_rect, new_x, new_width, direction)
                if testing:
                    print(f'resize_pixels_relative: after left clip: {new_x=}, {new_width=}')

                new_y, new_height, resize_up_limit_reached = self._clip_up(rect, rect_id, parent_rect, new_y, new_height, direction)

                if testing:
                    print(f'resize_pixels_relative: before right clip: {new_x=}, {new_width=}')
                new_x, new_width, resize_right_limit_reached = self._clip_right(rect, rect_id, parent_rect, new_x, new_width, direction)
                if testing:
                    print(f'resize_pixels_relative: after right clip: {new_x=}, {new_width=}')

                new_y, new_height, resize_down_limit_reached = self._clip_down(rect, rect_id, parent_rect, new_y, new_height, direction)

                #print(f'resize_pixels_relative: from center')

            new_values = (new_x, new_y, new_width, new_height)

            if testing:
                #     print(f'move_pixels_relative: {delta_x=}, {delta_y=}, {delta_width=}, {delta_height=}')
                print(f'resize_pixels_relative: {width=}, {new_width=}, {height=}, {new_height=}')
                print(f'resize_pixels_relative: setting rect {new_values=}')

            result = False
            old_rect = rect
            try:
                # make it so
                result, rect = self.compass_control.set_rect(rect, rect_id, ui.Rect(*new_values))
            except CompassControl.RectUpdateError as e:
                self.compass_control._handle_rect_update_error(e)

            if not result and self.use_change_check_for_shrink:
                # shrink is a special case, need to detect when the rectangle has shrunk to a minimum by
                # watching expected values to see when they stop changing as requested.
                if self.continuous_width_increment < 0:
                    # if a change was requested and not delivered, i.e. if the requested value is not the same as the old one AND
                    # the requested value is not the same as the current value.
                    if (new_x != old_rect.x and rect.x == old_rect.x) and (new_width != old_rect.width and rect.width == old_rect.width):
                        resize_left_limit_reached = True
                        resize_right_limit_reached = True
                        if testing:
                            # print(f'resize_pixels_relative: horizontal shrink limit reached')
                            print(f'resize_pixels_relative: horizontal shrink limit reached - {rect.x=}, {new_x=}, {rect.width=}, {new_width=}')

                if self.continuous_height_increment < 0:
                    # if a change was requested and not delivered, i.e. if the requested value is not the same as the old one AND
                    # the requested value is not the same as the current value.
                    if (new_y != old_rect.y and rect.y == old_rect.y) and (new_height != old_rect.height and rect.height == old_rect.height):
                        resize_up_limit_reached = True
                        resize_down_limit_reached = True
                        if testing:
                            print(f'resize_pixels_relative: vertical shrink limit reached')

            elapsed_time_ms = (time.time_ns() - start_time) / 1e6
            if testing:
                print(f'resize_pixels_relative: done ({elapsed_time_ms} ms)')

            return result, rect, resize_left_limit_reached, resize_up_limit_reached, resize_right_limit_reached, resize_down_limit_reached

        # change size in given direction to match the given values
        def resize_absolute(self, rect_cc: ui.Rect, rect_id: int, target_width: float, target_height: float, region_in: Optional[Direction] = None) -> None:
            x = rect_cc.x
            y = rect_cc.y

            delta_width = target_width - rect_cc.width
            delta_height = target_height - rect_cc.height

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
                result, rect = self.compass_control.set_rect(rect_cc, rect_id, ui.Rect(round(x), round(y), round(target_width), round(target_height)))
            except CompassControl.RectUpdateError as e:
                self.compass_control._handle_rect_update_error(e)

            if testing:
                print(f'resize_absolute: {rect_cc=}')
                ctrl.mouse_move(rect_cc.x, rect_cc.y)


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

    # reset variables used during continuous operations
    def _reset_continuous_flags(self) -> None:
        with self.continuous_mutex:
            self.mover._reset_continuous()
            self.sizer._reset_continuous()
            
            self.continuous_direction = None
            self.continuous_old_rect = None
            self.continuous_iteration = 0
            self.continuous_rect = None
            self.continuous_rect_id = None
            self.continuous_parent_rect = None

    # restore state of rectangle from before the last change
    def revert(self, rect: ui.Rect, rect_id: int) -> None:
        if self.last_rect and self.last_rect['id'] == rect_id:
            if testing:
                print(f'revert: reverting size and/or position for {self.last_rect}')

            result = False
            try:
                result, rect = self.set_rect(rect, rect_id, self.last_rect['rect'])
            except CompassControl.RectUpdateError as e:
                self._handle_rect_update_error(e)            

    # move rectangle to center and size it according to the given direction and screen size percentage
    def snap(self, rect: ui.Rect, rect_id: int, parent_rect: ui.Rect, percent: int, direction: Direction) -> None:
        target_width = (parent_rect.width * (percent/100))
        target_height = (parent_rect.height * (percent/100))

        old_rect = rect 

        # move rectangle center to parent rectangle center
        self.mover.move_absolute(rect, rect_id, parent_rect.center.x, parent_rect.center.y, direction)

        # set rectangle size
        self.sizer.resize_absolute(rect, rect_id, target_width, target_height, direction)

        self.continuous_old_rect = old_rect

    # return midpoint of the rectangle edge indicated by the given direction
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

    # return coordinates of the rectangle corner indicated by the given direction
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

    # return coordinates of the rectangle center
    def get_center(self, rect_cc: ui.Rect) -> Tuple[float, float]:
        return rect_cc.center.x, rect_cc.center.y

    # return coordinates of the rectangle point indicated by the given direction
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

    # after a change, save state of the regional rectangle so it can be restored later
    def save_last_rect(self, rect_id=None, rect=None):
        # if testing:
        #     print(f'save_last_rect: {self}, {self.continuous_rect_id=}, {self.continuous_old_rect=}')
            
        if not rect_id:
            rect_id=self.continuous_rect_id
        if not rect:
            rect=self.continuous_old_rect

        self.last_rect = {
            'id': rect_id,
            'rect': rect
        }

    # stop the current continuous move/resize operation
    def continuous_stop(self) -> None:
        with self.continuous_mutex:
            if not self.mover.continuous_job and not self.sizer.continuous_job:
                if testing:
                    print('continuous_stop: no jobs to stop (may have stopped automatically via clipping logic)')
                return

            if testing:
                print(f'continuous_stop: current thread = {threading.get_native_id()}')

            if self.mover.continuous_job:
                cron.cancel(self.mover.continuous_job)

            if self.sizer.continuous_job:
                cron.cancel(self.sizer.continuous_job)

            # disable 'stop' command
            ctx.tags = []

            if self.continuous_old_rect:
                # remember starting rectangle
                if testing:
                    print(f'continuous_stop: {self.continuous_old_rect=}')

                self.save_last_rect()
                self.continuous_old_rect = None

            self._reset_continuous_flags()

            stop_method = self.continuous_stop_method
            stop_method()

    def get_diagonal_length(self, rect: ui.Rect) -> float:
        return math.sqrt(((rect.width - rect.x) ** 2) + ((rect.height - rect.y) ** 2))

    def get_center_to_center_rect(self, rect: ui.Rect, rect_id: int, other_rect: ui.Rect) -> Tuple[ui.Rect, bool, bool]:
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
        rect = rect_cc
        direction_count = sum(direction.values())
        if operation == 'move' and direction_count == 4:    # move to center
            # this is a special case - 'move center' - we return signed values for this case only

            rect, horizontal_multiplier, vertical_multiplier = self.get_center_to_center_rect(rect_cc, rect_id, parent_rect)
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

    def get_component_dimensions_by_percent(self, rect_cc: ui.Rect, rect_id: int, parent_rect: ui.Rect, percent: float, direction: Direction, operation: str) -> Tuple[int, int]:
        if testing:
            print(f'_get_component_dimensions_by_percent: {percent=}')

        rect = rect_cc
        direction_count = sum(direction.values())
        if operation == 'move' and direction_count == 4:    # move to center
            rect, *unused = self.get_center_to_center_rect(rect, rect_id, parent_rect)

        if direction_count  == 1:    # horizontal or vertical
            if direction["left"] or direction["right"]:
                distance = rect.width * (percent/100)
            elif direction["up"] or direction["down"]:
                distance =  rect.height * (percent/100)
        else:  # diagonal
            diagonal_length = self.get_diagonal_length(rect)
            distance = diagonal_length * (percent/100)

        return self.get_component_dimensions(rect_cc, rect_id, parent_rect, distance, direction, operation)

    def _get_continuous_parameters(self, rect: ui.Rect, rect_id: int, parent_rect: ui.Rect, rate_cps: float, dpi_x: float, dpi_y: float, direction: Direction, operation: str, frequency: float) -> Tuple[int, int]:
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
                width_increment = dpms_x * frequency
            elif direction["up"] or direction["down"]:
                height_increment = dpms_y * frequency
        else:    # diagonal
            width_increment = dpms_x * frequency
            height_increment = dpms_y * frequency

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

    def set_rect(self, old_rect: ui.Rect, rect_id: int, rect_in: ui.Rect) -> Tuple[bool, ui.Rect]:
        set_method = self.set_method
        result = set_method(old_rect, rect_id, rect_in)
        
        # remember old rectangle, for 'revert'
        self.last_rect = {
            'id': rect_id,
            'rect': old_rect
        }        

        return result

## talon stuff

mod = Module()

# # context used to enable/disable the tag for controlling whether the 'stop' command is active
ctx = Context()

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

# explicitly trigger re-import of dependent modules, since the talon reload mechanism won't do it
DEPENDENTS = [ 'window_tweak.py' ]

print(f'compass_control.py - triggering re-import of dependent modules: {DEPENDENTS}')
    
import os
from pathlib import Path

curdir = os.path.dirname(__file__)
for dependent in DEPENDENTS:
    Path(os.path.join(curdir, dependent)).touch()
