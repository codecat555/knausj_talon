"""
Tools for managing window size and position.
"""

from typing import Dict, Tuple, Optional

import time
import math
from talon import ui, Module, actions, speech_system, ctrl

Direction = Dict[str, bool]

testing = True

mod = Module()

# taken from https://talon.wiki/unofficial_talon_docs/#captures
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

def _win_move_pixels_relative(w: ui.Window, direction:Direction, delta_width: int, delta_height: int) -> None:
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
        test0 = False
        if test0:
            print(f'_win_move_pixels: before: {ui.active_window().rect=}')

        # WIP - clipping only added to avoid talon insert looping bug
        #new_x, new_y, delta_width, delta_height = clip_to_screen(new_x, new_y, new_width, new_height)

        w.rect = ui.Rect(new_x, new_y, w.rect.width, w.rect.height)
        if test0:
            actions.sleep("100ms")
            print(f'_win_move_pixels: after: {ui.active_window().rect=}')

def _win_size_pixels_relative(w: ui.Window, direction:Direction, delta_width: int, delta_height: int) -> None:
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

    #new_x, new_y, delta_width, delta_height = clip_to_screen(new_x, new_y, new_width, new_height)

    # make it so
    w.rect = ui.Rect(new_x, new_y, new_width, new_height)

def _get_component_distances(w:ui.Window, direction:Direction, distance:int):
        # are we moving diagonally?
        direction_count = sum(direction.values())

        delta_width = delta_height = 0
        if direction_count  > 1:    # diagonal    
            diagonal_length = math.sqrt(((w.rect.width - w.rect.x) ** 2) + ((w.rect.height - w.rect.y) ** 2))
            ratio = distance / diagonal_length
            delta_width = w.rect.width * ratio
            delta_height = w.rect.height * ratio
        else:  # horizontal or vertical  
            if direction["left"] or direction["right"]:
                delta_width = distance
            elif direction["up"] or direction["down"]:
                delta_height = distance

        return delta_width, delta_height

def _translate_top_left_by_region(w:ui.Window, x:int, y:int, direction:Direction) -> Tuple[int, int]:
    
    width = w.rect.width
    height = w.rect.height

    if testing:
        actions.insert(f"_translate_top_left_by_region: initial position: {x=}, {y=}, {width=}, {height=}\n")
    
    direction_count = sum(direction.values())
    if direction_count == 1:
        if direction["left"]:
            y = y - int((height/2))
        
        elif direction["right"]:
            x = x - width
            y = y - int((height/2))

        elif direction["up"]:
            x = x - int((width/2))
        
        elif direction["down"]:
            x = x - int((width/2))
            y = y - height
    
    elif direction_count == 2:
        if direction["left"] and direction["up"]:
            # nothing to do here x and y are already set correctly for this case
            pass

        elif direction["right"] and direction["up"]:
            x = x - width

        elif direction["right"] and direction["down"]:
            x = x - width
            y = y - height

        elif direction["left"] and direction["down"]:
            y = y - height

    elif direction_count == 4:
        x = x - int((width/2))
        y = y - int((height/2))
        
    if testing:
        actions.insert(f"_translate_top_left_by_region: translated position: {x=}, {y=}, {width=}, {height=}\n")
        
    return x, y

def _clip_to_screen(w:ui.Window, x: int, y: int) -> Tuple[int, int]:
    screen = w.screen.visible_rect
    if x < screen.x:
        if testing:
            actions.insert(f'x too small, clipping: {x,y}\n')
        x = screen.x
    elif x > screen.x + screen.width:
        if testing:
            actions.insert(f'x too big, clipping: {x,y}\n')
        x = screen.x + screen.width
    elif y < screen.y:
        if testing:
            actions.insert(f'y too small, clipping: {x,y}\n')
        y = screen.y
    elif y > screen.y + screen.height:
        if testing:
            actions.insert(f'y too big, clipping: {x,y}\n')
        y = screen.y + screen.height

    return x, y

# phrase management code lifted from history.py
def parse_phrase(word_list):
    return " ".join(word.split("\\")[0] for word in word_list)

def on_phrase(j):
    global last_phrase

    last_phrase = ""
    try:
        last_phrase = parse_phrase(getattr(j["parsed"], "_unmapped", j["phrase"]))
    except:
        last_phrase = parse_phrase(j["phrase"])

speech_system.register("phrase", on_phrase)

@mod.action_class
class Actions:
    def win_move_absolute(x_in:int, y_in:int, region:Optional[Direction] = None) -> None:
        "Move window to given absolute position, centered on the point by the given region"
        w = ui.active_window()
        x = x_in
        y = y_in

        if testing:
            actions.insert(f'cmd: "{last_phrase}"\n')

        # find the point which we will move to the given coordinates, as indicated by the region.
        if region:
            x, y = _translate_top_left_by_region(w, x, y, region)

            if testing:
                actions.insert(f'translated top left position: {x,y}\n')
        
        w.rect = ui.Rect(x, y, w.rect.width, w.rect.height)

        if testing:
            while not w.rect.x == x and not w.rect.y == y:
                actions.insert(f'{time.time()} waiting for changes to take effect: {ui.active_window().rect=}\n')
            # need to wait just a bit longer before the change is stable...otherwise the subsequent insert
            # will not always reflect the updated values
            actions.sleep("50ms")
            actions.insert(f'result: {w.rect}\n\n')
            ctrl.mouse_move(x_in, y_in)
    
    def win_size_absolute(width:int, height:int, region:Optional[Direction] = None) -> None:
        "Size window to given absolute dimensions, optionally by stretching/shrinking in the direction indicated by the given region"
        w = ui.active_window()

        if testing:
            actions.insert(f'cmd: "{last_phrase}"\n')

        # find the point which we will move to the given coordinates, as indicated by the region.
        x = w.rect.x
        y = w.rect.y
        if region:
            x, y = _translate_top_left_by_region(w, x, y, region)
            
            if testing:
                actions.insert(f'translated top left position: ({x,y})\n')

        #x, y = _clip_to_screen(w, x, y)

        w.rect = ui.Rect(x, y, width, height)
            
        if testing:
            while not w.rect.width == width and not w.rect.height == height:
                actions.insert(f'{time.time()} waiting for changes to take effect: {ui.active_window().rect=}\n')
            # need to wait just a bit longer before the change is stable...otherwise the subsequent insert
            # will not always reflect the updated values
            actions.sleep("50ms")
            actions.insert(f'result: {w.rect}\n\n')

    def win_test_reset() -> None:
        "reset size and position of test window"
        # make it so
        w = ui.active_window()
        w.rect = ui.Rect(100,100,1000,1000)
        while not ui.active_window().rect.x == 100 and not ui.active_window().rect.y == 100 and not ui.active_window().rect.width == 1000 and not ui.active_window().rect.height == 1000:
            print(f'reset test window: {ui.active_window().rect=}')
        print(f'reset test window: {ui.active_window().rect=}')

    def win_move_pixels(direction:Direction, distance: int) -> None:
        "move window some number of pixels"
        w = ui.active_window()

        delta_width, delta_height = _get_component_distances(w, direction, distance)

        _win_move_pixels_relative(w, direction, delta_width, delta_height)
    
    def win_move_percent(direction:Direction, percent:int) -> None:
        "move window some percentage of the current size"

        w = ui.active_window()

        delta_width = w.rect.width * (percent/100)
        delta_height = w.rect.height * (percent/100)

        _win_move_pixels_relative(w, direction, delta_width, delta_height)  
    
    def win_size_pixels(direction:Direction, distance: int) -> None:
        "change window size by pixels"
        w = ui.active_window()
        
        delta_width, delta_height = _get_component_distances(w, direction, distance)

        _win_size_pixels_relative(w, direction, delta_width, delta_height)

    def win_size_percent(direction:Direction, percent:int) -> None:
        "change window size by a percentage of current size"
        
        w = ui.active_window()

        delta_width = w.rect.width * (percent/100)
        delta_height = w.rect.height * (percent/100)

        _win_size_pixels_relative(w, direction, delta_width, delta_height)

    def win_snap_percent(percent: int) -> None:
        "change window size to some percentage of parent screen (in each direction)"

        direction = compass_direction(['all'])
        
        w = ui.active_window()

        delta_width = (w.screen.visible_rect.width * (percent/100)) - w.rect.width
        delta_height = (w.screen.visible_rect.height * (percent/100)) - w.rect.height
        
        _win_size_pixels_relative(w, direction, delta_width, delta_height)

    def win_revert() -> None:
        "restore current window's last remembered size and position"
        print('not implemented yet')