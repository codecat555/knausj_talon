"""
Tools for managing window size and position.

Continuous move/resize machinery adapted from mouse.py.
"""

# WIP - modify clipping to support multiple screens
# WIP - use a mod or scope to disable all voice commands during a
# WIP - continuous move/resize operation...except 'win stop', etc.
# WIP - refactor into classes, move globals into class or instance variables

from typing import Dict, List, Tuple, Optional

import math
import queue
import logging
import sys

from talon import ui, Module, actions, speech_system, ctrl, imgui, cron, settings, app
from talon.debug import log_exception

# a type for representing compass directions
Direction = Dict[str, bool]

# turn debug messages on and off
testing = True

# remember the last window for use by the 'win revert' command
last_window: Dict = None

# globals used by the continuous move/resize commands
move_width_increment = 0
move_height_increment = 0
resize_width_increment = 0
resize_height_increment = 0
move_job = None
resize_job = None
continuous_direction = None
continuous_old_rect = None
# use window size history to detect when the window stops shrinking during resize,
# i.e. the minimum size has been reached and the resize operation should stop.
resize_history = []

# user notification definitions
# WIP - why not just let 'win move center' move toward the center of the screen?
center_move_not_valid_title = 'Talon - Cannot move all directions at once'
center_move_not_valid_body = 'The "center" direction is not valid for move operations.'

mod = Module()

mod.setting(
    "win_continuous_move_increment",
    type=int,
    default=1,
    desc="The percent increment used when moving a window continuously",
)
mod.setting(
    "win_continuous_resize_increment",
    type=int,
    default=1,
    desc="The percent increment used when resizing a window continuously",
)
mod.setting(
    "win_move_frequency",
    type=str,
    default="100ms",
    desc="The update frequency used when moving a window continuously",
)
mod.setting(
    "win_resize_frequency",
    type=str,
    default="100ms",
    desc="The update frequency used when resizing a window continuously",
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

@imgui.open(y=0)
def _win_stop_gui(gui: imgui.GUI) -> None:
    gui.text(f"Say 'win stop' or click below.")
    gui.line()
    if gui.button("Stop moving/resizing"):
        actions.user.win_stop()

def _win_move_continuous_helper() -> None:
    # print("win_move_continuous_helper")
    if move_width_increment or move_height_increment:
        w = ui.active_window()
        _win_move_pixels_relative(w, move_width_increment, move_height_increment, continuous_direction)
    else:
        # WIP - why not just call stop here?
        pass

def _win_resize_continuous_helper() -> None:
    global resize_history

    # print("win_resize_continuous_helper")
    if resize_width_increment or resize_height_increment:
        w = ui.active_window()
        _win_resize_pixels_relative(w, resize_width_increment, resize_height_increment, continuous_direction)

        value = (w.rect.width, w.rect.height)
        if len(resize_history) == 2:
            if value == resize_history[0] == resize_history[1]:
                # window size has stopped changing...so quit trying
                if testing:
                    print('window size has stopped changing, quitting...')
                actions.user.win_stop()
                resize_history = []
            else:
                # chuck old data to make room for new data
                resize_history.pop(0)
        #
        # keep history
        resize_history.append(value)
    else:
        # WIP - why not just call stop here?
        pass

def _start_move() -> None:
    global move_job
    move_job = cron.interval(settings.get('user.win_move_frequency'), _win_move_continuous_helper)

def _start_resize() -> None:
    global resize_job, reresize_historyy

    resize_history = []
    resize_job = cron.interval(settings.get('user.win_resize_frequency'), _win_resize_continuous_helper)

def _win_move_continuous(w: ui.Window, direction: Direction) -> None:
    global move_width_increment, move_height_increment, continuous_direction, continuous_old_rect

    if not move_job is None:
        logging.warning('cannot start a move job when one is already running')
        return

    continuous_direction = direction

    continuous_old_rect = w.rect

    move_width_increment, move_height_increment = _get_component_dimensions_by_percent(w, settings.get('user.win_continuous_move_increment'), direction)

    _start_move()

    if settings.get('user.win_hide_move_gui') == 0:
        _win_stop_gui.show()

def _win_resize_continuous(w: ui.Window, multiplier: int, direction: Optional[Direction] = None) -> None:
    global resize_width_increment, resize_height_increment, continuous_direction, continuous_old_rect

    if testing:
        print(f'_win_resize_continuous: starting resize - {resize_width_increment=}, {resize_height_increment=}, {continuous_direction=}, {multiplier=}')

    # WIP - TOUTOC issue here with resize_job, use mutex?
    if not resize_job is None:
        logging.warning('cannot start a resize job when one is already running')
        return

    resize_width_increment, resize_height_increment = \
        _get_component_dimensions_by_percent(w, settings.get('user.win_continuous_resize_increment'), direction)
    # apply multiplier to control whether we're stretching or shrinking
    resize_width_increment *= multiplier
    resize_height_increment *= multiplier
        
    continuous_direction = direction

    continuous_old_rect = w.rect

    _start_resize()

    if settings.get('user.win_hide_resize_gui') == 0:
        _win_stop_gui.show()

def _win_stop() -> None:
    global move_width_increment, move_height_increment, resize_width_increment, resize_height_increment, move_job, resize_job
    global last_window, continuous_direction, continuous_old_rect

    if not move_job and not resize_job:
        if testing:
            print('_win_stop: no jobs to stop (may have stopped automatically via clipping logic)')
        return

    if move_job:
        cron.cancel(move_job)

    if resize_job:
        cron.cancel(resize_job)

    move_width_increment = 0
    move_height_increment = 0
    resize_width_increment = 0
    resize_height_increment = 0
    move_job = None
    resize_job = None
    continuous_direction = None

    #actions.sleep('100ms')

    if continuous_old_rect:
        # remember starting rectangle
        print(f'_win_stop: {continuous_old_rect=}')
        last_window = {
            'id': ui.active_window().id,
            'rect': continuous_old_rect
        }
        continuous_old_rect = None

    _win_stop_gui.hide()

def _clip_to_screen_for_move(w, x: int, y: int, width: int, height: int) -> Tuple[int, int]:
    screen = w.screen
    screen_x = int(screen.visible_rect.x)
    screen_y = int(screen.visible_rect.y)
    screen_width = int(screen.visible_rect.width)
    screen_height = int(screen.visible_rect.height)

    new_x = x
    new_y = y
    if x < screen_x:
        new_x = screen_x
    elif x > screen_x + screen_width - width:
        new_x = screen_x + screen_width - width

    if y < screen_y:
        new_y = screen_y
    elif y > screen_y + screen_height - height:
        new_y = screen_y + screen_height - height
        
    return new_x, new_y

def _win_move_pixels_relative(w: ui.Window, delta_x: int, delta_y: int, direction: Direction) -> None:
        global move_width_increment, move_height_increment

        # start with the current values
        x = w.rect.x
        y = w.rect.y
        
        # apply changes as indicated
        if direction["left"]:
            x -= delta_x
        elif direction["right"]:
            x += delta_x
        #
        if direction["up"]:
            y -= delta_y
        elif direction["down"]:
            y += delta_y

        new_x, new_y = _clip_to_screen_for_move(w, x, y, w.rect.width, w.rect.height)
        
        # print(f'_win_move_pixels_relative: {x=},  {y=}, {new_x=}, {new_y=}')
        #
        if new_x != x:
            # done moving horizontally
            move_width_increment = 0
        #
        if new_y != y:
            # done moving vertically
            move_height_increment = 0

        # if testing:
        #     print(f'_win_move_pixels_relative: before: {w.rect=}')
        #     #print(f'_win_move_pixels_relative: {new_x=}, {new_y=}')

        # make it so
        _win_set_rect(w, ui.Rect(new_x, new_y, w.rect.width, w.rect.height))

        # if testing:
        #     print(f'_win_move_pixels_relative: after: {w.rect=}')

        # WIP - maybe do this in _win_move_continuous_helper()?
        if move_width_increment == 0 and move_height_increment == 0:
            # stop when there's nothing left to do
            actions.user.win_stop()

def _get_diagonal_length(w: ui.Window) -> int:
    return math.sqrt(((w.rect.width - w.rect.x) ** 2) + ((w.rect.height - w.rect.y) ** 2))

def _get_component_dimensions(w: ui.Window, distance: int, direction: Direction) -> Tuple[int, int]:
    # are we moving diagonally?
    direction_count = sum(direction.values())

    delta_width = delta_height = 0
    if direction_count  > 1:    # diagonal
        diagonal_length = _get_diagonal_length(w)
        ratio = distance / diagonal_length
        delta_width = round(w.rect.width * ratio)
        delta_height = round(w.rect.height * ratio)
    else:  # horizontal or vertical
        if direction["left"] or direction["right"]:
            delta_width = distance
        elif direction["up"] or direction["down"]:
            delta_height = distance

    if testing:
        print(f"_get_component_dimensions: returning {delta_width}, {delta_height}\n")

    return delta_width, delta_height

def _get_component_dimensions_by_percent(w: ui.Window, percent: int, direction: Direction) -> Tuple[int, int]:
    if testing:
        print(f'_get_component_dimensions_by_percent: {percent=}')

    direction_count = sum(direction.values())
    if direction_count  > 1:    # diagonal
        diagonal_length = _get_diagonal_length(w)
        distance = round(diagonal_length * (percent/100))
    else:  # horizontal or vertical
        if direction["left"] or direction["right"]:
            distance = round(w.rect.width * (percent/100))
        elif direction["up"] or direction["down"]:
            distance =  round(w.rect.height * (percent/100))

    return _get_component_dimensions(w, distance, direction)

def _translate_top_left_by_region_for_move(w: ui.Window, target_x: int, target_y: int, direction: Direction) -> Tuple[int, int]:

    width = w.rect.width
    height = w.rect.height

    if testing:
        print(f"_translate_top_left_by_region_for_move: initial rect: {w.rect}\n")
        print(f"_translate_top_left_by_region_for_move: move coordinates: {target_x=}, {target_y=}\n")

    direction_count = sum(direction.values())
    if direction_count == 1:
        if direction["left"]:
            target_y = target_y - height // 2

        elif direction["right"]:
            target_x = target_x - width
            target_y = target_y - height // 2

        elif direction["up"]:
            target_x = target_x - width // 2

        elif direction["down"]:
            target_x = target_x - width // 2
            target_y = target_y - height

    elif direction_count == 2:
        if direction["left"] and direction["up"]:
            # nothing to do here x and y are already set correctly for this case
            pass

        elif direction["right"] and direction["up"]:
            target_x = target_x - width

        elif direction["right"] and direction["down"]:
            target_x = target_x - width
            target_y = target_y - height

        elif direction["left"] and direction["down"]:
            target_y = target_y - height

    elif direction_count == 4:
        target_x = target_x - width // 2
        target_y = target_y - height // 2

    if testing:
        print(f"_translate_top_left_by_region_for_move: translated position: {target_x=}, {target_y=}, {width=}, {height=}\n")

    return target_x, target_y

def _translate_top_left_by_region_for_resize(w: ui.Window, target_width: int, target_height: int, direction: Direction) -> Tuple[int, int]:

    x = w.rect.x
    y = w.rect.y

    delta_width = target_width - w.rect.width
    delta_height = target_height - w.rect.height

    if testing:
        print(f"_translate_top_left_by_region_for_resize: initial rect: {w.rect}\n")
        print(f"_translate_top_left_by_region_for_resize: resize coordinates: {target_width=}, {target_height=}\n")

    direction_count = sum(direction.values())
    if direction_count == 1:
        if direction["left"]:
            # stretching west, x coordinate must not change for the eastern corners, so push top left to the west
            x = x - delta_width

            # adjust y to account for half the change in height
            y = y - delta_height // 2

        elif direction["up"]:
            # stretching north, y coordinate must not change for the southern corners,
            # adjust x to account for half the change in width
            x = x - delta_width // 2

            # adjust y to account for the entire change in height
            y = y - delta_height

        elif direction["right"]:
            # we are stretching east, so the x coordinate must not change for the western corners, i.e. top left

            # adjust y to account for half the change in height
            y = y - delta_height // 2

        elif direction["down"]:
            # stretching south, y coordinate must not change for the northern corners, i.e. top left

            # adjust x to account for half the change in width
            x = x - delta_width // 2

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
        x = x - delta_width // 2
        y = y - delta_height // 2

    if testing:
        print(f"_translate_top_left_by_region_for_resize: translated position: {x=}, {y=}, {target_width=}, {target_height=}\n")

    return x, y

def _win_set_rect(w: ui.Window, rect_in: ui.Rect) -> None:
    if not rect_in:
        raise ValueError('rect_in is None')

    # adapted from https: // talonvoice.slack.com/archives/C9MHQ4AGP/p1635971780355900
    q = queue.Queue()
    def on_update(event_win: ui.Window) -> None:
        if event_win == w and w.rect != old_rect:
            q.put(1)
    #
    old_rect = w.rect
    event_count = 0
    if (rect_in.x, rect_in.y) != (w.rect.x, w.rect.y):
        ui.register('win_move',   on_update)
        event_count += 1
    if (rect_in.width, rect_in.height) != (w.rect.width, w.rect.height):
        ui.register('win_resize', on_update)
        event_count += 1
    if event_count == 0:
        # no real work to do
        return

    w.rect = rect_in
    try:
        # for testing
        #raise queue.Empty()
        #raise Exception('just testing')

        q.get(timeout=0.3)
        if event_count == 2:
            q.get(timeout=0.3)

    except queue.Empty:
        logging.warning('_win_set_rect: timed out waiting for window update')
    except:
        log_exception(f'{sys.exc_info()[1]}')
    else:
        # if testing:
        #     print(f'_win_set_rect: {old_rect=}, {rect_in=}')

        # results are not guaranteed, warn if the request could not be fulfilled exactly
        if (rect_in.x, rect_in.y) != (w.rect.x, w.rect.y):
            if testing:
                print(f'_win_set_rect: {rect_in=}')
                
            logging.warning('after update, window position does not exactly match request')
            
        if (rect_in.width, rect_in.height) != (w.rect.width, w.rect.height):
            if testing:
                print(f'_win_set_rect: {rect_in=}')

            # warning below disabled because it happens normally in the course of shrinking
            # a window (when it has reached minimal size).
            #logging.warning('_win_set_rect: after update, window size does not exactly match request')

    finally:
        # remember old rectangle, for 'win revert'
        global last_window
        #print(f'_win_set_rect: {old_rect=}')
        last_window = {
            'id': w.id,
            'rect': old_rect
        }
        
        ui.unregister('win_move',   on_update)
        ui.unregister('win_resize', on_update)

def _clip_left_for_resize(w: ui.Window, x: int, width: int) -> Tuple[int, int]:
    global resize_width_increment

    screen_x = int(w.screen.visible_rect.x)
    
    # clip to screen
    if x < screen_x:
        # print(f'_clip_left: left clipping')

        # update width before updating new_x
        width = width - (x - screen_x)
        x = screen_x

        # # done changing horizontally
        resize_width_increment = 0

    return x, width

def _clip_up_for_resize(w: ui.Window, y: int, height: int) -> Tuple[int, int]:
    global resize_height_increment

    screen_y = int(w.screen.visible_rect.y)

    # clip to screen
    if y < screen_y:
        # print(f'_clip_up: up clipping')
        
        # update height before updating y
        height = height - (screen_y - y)
        y = screen_y

        # # done changing vertically
        resize_height_increment = 0

    return y, height

def _clip_right_for_resize(w: ui.Window, x: int, width: int) -> Tuple[int, int]:
    global resize_width_increment

    screen_x = int(w.screen.visible_rect.x)
    screen_width = int(w.screen.visible_rect.width)

    if x + width > screen_x + screen_width:
        # print(f'_clip_right: right clipping')
        
        width = screen_x + screen_width - x

        # done changing horizontally
        resize_width_increment = 0

    return x, width

def _clip_down_for_resize(w: ui.Window, y: int, height: int) -> Tuple[int, int]:
    global resize_height_increment

    screen_y = int(w.screen.visible_rect.y)
    screen_height = int(w.screen.visible_rect.height)

    if y + height > screen_y + screen_height:
        # print(f'_clip_down: down clipping')

        height = screen_y + screen_height - y

        # done changing vertically
        resize_height_increment = 0

    return y, height
    
def _win_resize_pixels_relative(w: ui.Window, delta_width: int, delta_height: int, direction_in: Direction) -> None:
    global resize_width_increment, resize_height_increment
 
    # start with the current values
    x = new_x = w.rect.x
    y = new_y = w.rect.y
    width = new_width = w.rect.width + delta_width
    height = new_height = w.rect.height + delta_height

    # print(f'_win_resize_pixels_relative: {delta_width=}, {delta_height=}')

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

    screen = w.screen
    screen_x = int(screen.visible_rect.x)
    screen_y = int(screen.visible_rect.y)
    screen_width = int(screen.visible_rect.width)
    screen_height = int(screen.visible_rect.height)

    # are we moving diagonally?
    direction_count = sum(direction.values())
    #print(f'_win_resize_pixels_relative: {direction_count=}')

    if direction_count == 1:    # horizontal or vertical
        # print(f'_win_resize_pixels_relative: single direction (horizontal or vertical)')
        # apply changes as indicated
        if direction["left"]:
            new_x = new_x - delta_width
            new_x, new_width = _clip_left_for_resize(w, new_x, new_width)
        #
        if direction["up"]:
            new_y = new_y - delta_height
            new_y, new_height = _clip_up_for_resize(w, new_y, new_height)
        #
        if direction["right"]:
            new_x, new_width = _clip_right_for_resize(w, new_x, new_width)
        #
        if direction["down"]:
            new_height = new_height + delta_height
            new_y, new_height = _clip_down_for_resize(w, new_y, new_height)

    elif direction_count == 2:    # stretch diagonally
        if direction["left"] and direction["up"]:
            # we are stretching northwest so the coordinates must not change for the southeastern corner
            new_x = new_x - delta_width
            new_y = new_y - delta_height

            new_x, new_width = _clip_left_for_resize(w, new_x, new_width)
            new_y, new_height = _clip_up_for_resize(w, new_y, new_height)

            #print(f'_win_resize_pixels_relative: left and up')

        elif direction["right"] and direction["up"]:
            # we are stretching northeast so the coordinates must not change for the southwestern corner

            # adjust y to account for the entire change in height
            new_y = new_y - delta_height

            new_x, new_width = _clip_right_for_resize(w, new_x, new_width)
            new_y, new_height = _clip_up_for_resize(w, new_y, new_height)

            #print(f'_win_resize_pixels_relative: right and up')

        elif direction["right"] and direction["down"]:
            # we are stretching southeast so the coordinates must not change for the northwestern corner,
            # nothing to do here x and y are already set correctly for this case
            new_x, new_width = _clip_right_for_resize(w, new_x, new_width)
            new_y, new_height = _clip_down_for_resize(w, new_y, new_height)            

            #print(f'_win_resize_pixels_relative: right and down')

        elif direction["left"] and direction["down"]:
            # we are stretching southwest so the coordinates must not change for the northeastern corner,
            # adjust x to account for the entire change in width
            new_x = new_x - delta_width

            new_x, new_width = _clip_left_for_resize(w, new_x, new_width)
            new_y, new_height = _clip_down_for_resize(w, new_y, new_height)            

            #print(f'_win_resize_pixels_relative: left and down')

    elif direction_count == 4:    # stretch from center
        new_x = new_x - delta_width // 2
        new_y = new_y - delta_height // 2

        # WIP - this is clunky, but works...clean it up later
        save_width = resize_width_increment
        save_height = resize_height_increment

        horizontal_limit_reached = 0
        vertical_limit_reached = 0
        #
        new_x, new_width = _clip_left_for_resize(w, new_x, new_width)
        if (new_x, new_width) != (x, width):
        # if new_x != x:
            horizontal_limit_reached += 1
        #
        new_y, new_height = _clip_up_for_resize(w, new_y, new_height)
        if (new_y, new_height) != (y, height):
        # if new_y != y:
            vertical_limit_reached += 1
            
        new_x, new_width = _clip_right_for_resize(w, new_x, new_width)
        # if (new_x, new_width) != (x, width):
        if new_width != width:
            horizontal_limit_reached += 1

        new_y, new_height = _clip_down_for_resize(w, new_y, new_height)
        # if (new_y, new_height) != (y, height):
        if new_height != height:
            vertical_limit_reached += 1

        if new_x != screen_x or new_x + new_width != screen_x + screen_width:
            resize_width_increment = save_width

        if new_y != screen_y or new_y + new_height != screen_y + screen_height:
            resize_height_increment = save_height

        #print(f'_win_resize_pixels_relative: from center')

    # verbose, but useful sometimes
    # if testing:
    #     print(f'_win_resize_pixels_relative: before: {w.rect=}')

    # make it so
    _win_set_rect(w, ui.Rect(new_x, new_y, new_width, new_height))

    # verbose, but useful sometimes
    # if testing:
    #     print(f'_win_resize_pixels_relative: after: {w.rect=}')

    # WIP - maybe do this in _win_resize_continuous_helper()?
    if resize_width_increment == 0 and resize_height_increment == 0:
        # stop when there's nothing left to do
        actions.user.win_stop()
        # print(f'_win_resize_pixels_relative: stopped')

def _move_direction_check(direction: Direction) -> bool:
    direction_count = sum(direction.values())
    if direction_count == 4:
        app.notify(
            title=center_move_not_valid_title,
            body=center_move_not_valid_body
        )
        return False
    return True

@imgui.open(y=0)
def _win_show(gui: imgui.GUI) -> None:
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
    gui.text(f"Center: {x + width//2, y + height//2}")
    gui.spacer()

    gui.text(f"Width: {width}")
    gui.text(f"Height: {height}")

    gui.line()

    screen = w.screen
    gui.text(f"== Screen ==")
    gui.spacer()

    #gui.text(f"Name: {screen.name}")
    #gui.text(f"DPI: {screen.dpi}")
    #gui.text(f"Scale: {screen.scale}")
    #gui.spacer()

    x = int(screen.visible_rect.x)
    y = int(screen.visible_rect.y)
    width = int(screen.visible_rect.width)
    height = int(screen.visible_rect.height)

    gui.text(f"__Visible Rectangle__")
    gui.text(f"Top Left: {x, y}")
    gui.text(f"Top Right: {x + width, y}")
    gui.text(f"Bottom Left: {x, y + height}")
    gui.text(f"Bottom Right: {x + width, y + height}")
    gui.text(f"Center: {x + width//2, y + height//2}")
    gui.spacer()
    
    gui.text(f"Width: {width}")
    gui.text(f"Height: {height}")
    
    gui.spacer()

    x = int(screen.rect.x)
    y = int(screen.rect.y)
    width = int(screen.rect.width)
    height = int(screen.rect.height)

    gui.text(f"__Physical Rectangle__")
    gui.text(f"Top Left: {x, y}")
    gui.text(f"Top Right: {x + width, y}")
    gui.text(f"Bottom Left: {x, y + height}")
    gui.text(f"Bottom Right: {x + width, y + height}")
    gui.text(f"Center: {x + width//2, y + height//2}")
    gui.spacer()

    gui.text(f"Width: {width}")
    gui.text(f"Height: {height}")
    
    gui.line()

    gui.text(f"Say 'win hide' to close this window.")

    gui.line()

    if gui.button("Close"):
        _win_show.hide()

@mod.action_class
class Actions:
    def win_show() -> None:
        "Shows information about current window position and size"
        _win_show.show()

    def win_hide() -> None:
        "Hides the window information window"
        _win_show.hide()

    def win_stop() -> None:
        "Stops current window move/resize operation"
        _win_stop()

    def win_move(direction: Optional[Direction] = None) -> None:
        "Move window in small increments in the given direction, until stopped"

        if not _move_direction_check(direction):
            return

        w = ui.active_window()
        _win_move_continuous(w, direction)

    def win_move_absolute(x_in: int, y_in: int, region: Optional[Direction] = None) -> None:
        "Move window to given absolute position, centered on the point indicated by the given region"

        w = ui.active_window()
        x = x_in
        y = y_in

        # find the point which we will move to the given coordinates, as indicated by the region.
        if region:
            x, y = _translate_top_left_by_region_for_move(w, x, y, region)

            if testing:
                print(f'win_move_absolute: translated top left position: {x,y}\n')

        _win_set_rect(w, ui.Rect(x, y, w.rect.width, w.rect.height))

        if testing:
            print(f'win_move_absolute: {w.rect=}\n\n')
            ctrl.mouse_move(x_in, y_in)

    def win_stretch(direction: Optional[Direction] = None) -> None:
        "Stretch window in small increments until stopped, optionally in the given direction"

        if not direction:
            direction = compass_direction(['center'])

        w = ui.active_window()
        _win_resize_continuous(w, 1, direction)

    def win_shrink(direction: Optional[Direction] = None) -> None:
        "Shrink window in small increments until stopped, optionally in the given direction"
        w = ui.active_window()

        if not direction:
            direction = compass_direction(['center'])

        _win_resize_continuous(w, -1, direction)

    def win_resize_absolute(target_width: int, target_height: int, region_in: Optional[Direction] = None) -> None:
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

            x, y = _translate_top_left_by_region_for_resize(w, target_width, target_height, region)

            if testing:
                print(f'win_resize_absolute: translated top left position: {x,y}\n')

        _win_set_rect(w, ui.Rect(x, y, target_width, target_height))

        if testing:
            print(f'win_resize_absolute: {w.rect=}\n\n')
            ctrl.mouse_move(w.rect.x, w.rect.y)

    def win_move_pixels(distance: int, direction: Direction) -> None:
        "move window some number of pixels"

        if not _move_direction_check(direction):
            return

        w = ui.active_window()

        delta_width, delta_height = _get_component_dimensions(w, distance, direction)

        _win_move_pixels_relative(w, delta_width, delta_height, direction)

    def win_move_percent(percent: int, direction: Direction) -> None:
        "move window some percentage of the current size"

        if not _move_direction_check(direction):
            return

        w = ui.active_window()

        delta_width = w.rect.width * (percent/100)
        delta_height = w.rect.height * (percent/100)

        _win_move_pixels_relative(w, delta_width, delta_height, direction)

    def win_resize_pixels(distance: int, direction: Direction) -> None:
        "change window size by pixels"
        w = ui.active_window()

        delta_width, delta_height = _get_component_dimensions(w, distance, direction)

        if testing:
            print(f'win_resize_pixels: {delta_width=}, {delta_height=}')

        _win_resize_pixels_relative(w, delta_width, delta_height, direction)

    def win_resize_percent(percent: int, direction: Direction) -> None:
        "change window size by a percentage of current size"

        w = ui.active_window()

        delta_width, delta_height = _get_component_dimensions_by_percent(w, percent, direction)

        if testing:
            print(f'win_resize_percent: {delta_width=}, {delta_height=}')

        _win_resize_pixels_relative(w, delta_width, delta_height, direction)

    def win_snap_percent(percent: int) -> None:
        "change window size to some percentage of parent screen (in each direction)"

        direction = compass_direction(['center'])

        w = ui.active_window()

        delta_width = (w.screen.visible_rect.width * (percent/100)) - w.rect.width
        delta_height = (w.screen.visible_rect.height * (percent/100)) - w.rect.height

        _win_resize_pixels_relative(w, delta_width, delta_height, direction)

    def win_revert() -> None:
        "restore current window's last remembered size and position"

        w = ui.active_window()

        if last_window and last_window['id'] == w.id:
            if testing:
                print(f'win_revert: reverting size and/or position for {last_window}')
            _win_set_rect(w, last_window['rect'])
