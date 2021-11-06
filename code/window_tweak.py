"""
Tools for managing window size and position.
"""

from typing import Dict, Tuple, Optional

import time
import math
import queue
import logging
import sys
from talon import ui, Module, actions, speech_system, ctrl
from talon.debug import log_exception

Direction = Dict[str, bool]

testing = True

last_window: Dict = None

mod = Module()

# taken from https: // talon.wiki/unofficial_talon_docs/#captures
@mod.capture(rule="all | ((north | south) [(east | west)] | east | west)")
def compass_direction(m) -> Direction:
    """
    Matches on a basic compass direction to return which keys should
    be pressed.
    """
    result = {}

    if "all" in m:
        result["up"] = result["down"] = result["right"] = result["left"] = True
    else:
        result = {
            "up": "north" in m,
            "down": "south" in m,
            "right": "east" in m,
            "left": "west" in m
        }

    return result

def _win_move_pixels_relative(w: ui.Window, direction: Direction, delta_width: int, delta_height: int) -> None:
        # start with the current values
        new_x = w.rect.x
        new_y = w.rect.y

        # apply changes as indicated
        if direction["left"]:
            new_x -= delta_width          
        elif direction["right"]:
            new_x += delta_width
        #          
        if direction["up"]:
            new_y -= delta_height
        elif direction["down"]:
            new_y += delta_height

        # make it so
        if testing:
            print(f'_win_move_pixels: before: {ui.active_window().rect=}')

        _win_set_rect(w, ui.Rect(new_x, new_y, w.rect.width, w.rect.height))
        
        if testing:
            print(f'_win_move_pixels: after: {ui.active_window().rect=}')

def _win_size_pixels_relative(w: ui.Window, delta_width: int, delta_height: int, direction: Direction) -> None:
    # start with the current values
    new_x = w.rect.x
    new_y = w.rect.y
    new_width = w.rect.width
    new_height = w.rect.height

    # invert directions when shrinking. that is, we are shrinking *toward* the
    #  given direction rather than shrinking away from that direction.
    if delta_width < 0:
        temp = direction["right"]
        direction["right"] = direction["left"]
        direction["left"] = temp
    #
    if delta_height < 0:
        temp = direction["up"]
        direction["up"] = direction["down"]
        direction["down"] = temp
    
    # apply changes as indicated
    if direction["left"]:
        new_x -= delta_width          
    #            
    if direction["up"]:
        new_y -= delta_height
    #
    if direction["left"] or direction["right"]:
        new_width += delta_width
    #
    if direction["up"] or direction["down"]:
        new_height += delta_height

    # make it so
    _win_set_rect(w, ui.Rect(new_x, new_y, new_width, new_height))

def _get_diagonal_length(w: ui.Window) -> int:
    return math.sqrt(((w.rect.width - w.rect.x) ** 2) + ((w.rect.height - w.rect.y) ** 2))

def _get_component_distances(w: ui.Window, distance: int, direction: Direction) -> Tuple[int, int]:
    # are we moving diagonally?
    direction_count = sum(direction.values())

    delta_width = delta_height = 0
    if direction_count  > 1:    # diagonal    
        diagonal_length = _get_diagonal_length(w)
        ratio = distance / diagonal_length
        delta_width = w.rect.width * ratio
        delta_height = w.rect.height * ratio
    else:  # horizontal or vertical  
        if direction["left"] or direction["right"]:
            delta_width = distance
        elif direction["up"] or direction["down"]:
            delta_height = distance

    return delta_width, delta_height

def _get_component_percentages(w: ui.Window, percent: int, direction: Direction) -> Tuple[int, int]:
    direction_count = sum(direction.values())
    if direction_count  > 1:    # diagonal
        diagonal_length = _get_diagonal_length(w)
        distance = (diagonal_length * (percent/100))
    else:  # horizontal or vertical  
        if direction["left"] or direction["right"]:
            distance = (w.rect.width * (percent/100))
        elif direction["up"] or direction["down"]:
            distance =  (w.rect.height * (percent/100))
        
    return _get_component_distances(w, distance, direction)
        
def _translate_top_left_by_region_for_move(w: ui.Window, target_x: int, target_y: int, direction: Direction) -> Tuple[int, int]:
    
    width = w.rect.width
    height = w.rect.height

    if testing:
        print(f"_translate_top_left_by_region: initial rect: {w.rect}\n")
        print(f"_translate_top_left_by_region: move coordinates: {target_x=}, {target_y=}\n")
    
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
        print(f"_translate_top_left_by_region: translated position: {target_x=}, {target_y=}, {width=}, {height=}\n")
        
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
        
        elif direction["right"]:
            # we are stretching east, so the x coordinate must not change for the western corners, i.e. top left
            
            # adjust y to account for half the change in height
            y = y - delta_height // 2 

        elif direction["up"]:
            # stretching north, y coordinate must not change for the southern corners,
            # adjust x to account for half the change in width
            x = x - delta_width // 2  
            
            # adjust y to account for the entire change in height
            y = y - delta_height
        
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

def _win_set_rect(w: ui.Window, rect: ui.Rect) -> None:
    # adapted from https: // talonvoice.slack.com/archives/C9MHQ4AGP/p1635971780355900
    q = queue.Queue()
    def on_update(event_win):
        if event_win == w and w.rect != old_rect:
            q.put(1)
    #
    old_rect = w.rect
    event_count = 0
    if (rect.x, rect.y) != (w.rect.x, w.rect.y):
        ui.register('win_move',   on_update)
        event_count += 1
    if (rect.width, rect.height) != (w.rect.width, w.rect.height):
        ui.register('win_resize', on_update)
        event_count += 1
    if event_count == 0:
        # no real work to do
        return

    w.rect = rect
    try:
        # for testing
        #raise queue.Empty()
        #raise Exception('just testing') 

        q.get(timeout=0.3)
        if event_count == 2:
            q.get(timeout=0.3)
    except queue.Empty:
        logging.warning('timed out waiting for window update')
    except:
        log_exception(f'{sys.exc_info()[1]}')        
    else:
        # results are not guaranteed, warn if the request could not be fulfilled exactly
        if (rect.x, rect.y) != (w.rect.x, w.rect.y):
            logging.warning('after update, window position does not exactly match request')
        if (rect.width, rect.height) != (w.rect.width, w.rect.height):
            logging.warning('after update, window size does not exactly match request')

        # remember old rectangle
        global last_window
        last_window = {
            'id': w.id,
            'rect': old_rect
        }
    finally:
        ui.unregister('win_move',   on_update)
        ui.unregister('win_resize', on_update)

# phrase management code lifted from history.py
def parse_phrase(word_list):
    return " ".join(word.split("\\")[0] for word in word_list)
#
def on_phrase(j):
    global last_phrase

    last_phrase = ""
    try:
        last_phrase = parse_phrase(getattr(j["parsed"], "_unmapped", j["phrase"]))
    except:
        last_phrase = parse_phrase(j["phrase"])
#
speech_system.register("phrase", on_phrase)

@mod.action_class
class Actions:
    def win_move_absolute(x_in: int, y_in: int, region: Optional[Direction] = None) -> None:
        "Move window to given absolute position, centered on the point by the given region"
        w = ui.active_window()
        x = x_in
        y = y_in

        if testing:
            print(f'cmd: "{last_phrase}"\n')

        # find the point which we will move to the given coordinates, as indicated by the region.
        if region:
            x, y = _translate_top_left_by_region_for_move(w, x, y, region)

            if testing:
                print(f'translated top left position: {x,y}\n')
        
        _win_set_rect(w, ui.Rect(x, y, w.rect.width, w.rect.height))

        if testing:
            print(f'result: {w.rect}\n\n')
            ctrl.mouse_move(x_in, y_in)
    
    def win_size_absolute(target_width: int, target_height: int, region_in: Optional[Direction] = None) -> None:
        "Size window to given absolute dimensions, optionally by stretching/shrinking in the direction indicated by the given region"
        w = ui.active_window()

        if testing:
            print(f'cmd: "{last_phrase}"\n')

        # find the point which we will move to the given coordinates, as indicated by the region.
        x = w.rect.x
        y = w.rect.y
        delta_width = target_width - w.rect.width
        delta_height = target_height - w.rect.height

        region = region_in
        if region_in:
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
                print(f'translated top left position: {x,y}\n')

        _win_set_rect(w, ui.Rect(x, y, target_width, target_height))

        if testing:
            print(f'result: {w.rect}\n\n')
            ctrl.mouse_move(w.rect.x, w.rect.y)

    def win_move_pixels(distance: int, direction: Direction) -> None:
        "move window some number of pixels"
        w = ui.active_window()

        delta_width, delta_height = _get_component_distances(w, distance, direction)

        _win_move_pixels_relative(w, direction, delta_width, delta_height)
    
    def win_move_percent(percent: int, direction: Direction) -> None:
        "move window some percentage of the current size"

        w = ui.active_window()

        delta_width = w.rect.width * (percent/100)
        delta_height = w.rect.height * (percent/100)

        _win_move_pixels_relative(w, direction, delta_width, delta_height)  

    def win_size_pixels(distance: int, direction: Direction) -> None:
        "change window size by pixels"
        w = ui.active_window()
        
        delta_width, delta_height = _get_component_distances(w, distance, direction)

        print(f'win_size_pixels: {delta_width=}, {delta_height=}')

        _win_size_pixels_relative(w, delta_width, delta_height, direction)

    def win_size_percent(percent: int, direction: Direction) -> None:
        "change window size by a percentage of current size"
        
        w = ui.active_window()
        
        delta_width, delta_height = _get_component_percentages(w, percent, direction)
        
        print(f'win_size_percent: {delta_width=}, {delta_height=}')

        _win_size_pixels_relative(w, delta_width, delta_height, direction)

    def win_snap_percent(percent: int) -> None:
        "change window size to some percentage of parent screen (in each direction)"

        direction = compass_direction(['all'])
        
        w = ui.active_window()

        delta_width = (w.screen.visible_rect.width * (percent/100)) - w.rect.width
        delta_height = (w.screen.visible_rect.height * (percent/100)) - w.rect.height
        
        _win_size_pixels_relative(w, delta_width, delta_height, direction)

    def win_revert() -> None:
        "restore current window's last remembered size and position"
        
        w = ui.active_window()
        
        if last_window and last_window['id'] == w.id:
            if testing:
                print(f'reverting size and/or position for window {w.id}: {w.rect}')
            _win_set_rect(w, last_window['rect'])
        