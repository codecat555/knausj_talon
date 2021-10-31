"""
Tools for managing window size and position.
"""

from typing import Dict

import math
from talon import ui, Module, actions

Direction = Dict[str, bool]

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

def _win_move_pixels(w: ui.Window, direction:Direction, delta_width: int, delta_height: int) -> None:
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

        #new_x, new_y, delta_width, delta_height = clip_to_screen(new_x, new_y, new_width, new_height)

        w.rect = ui.Rect(new_x, new_y, w.rect.width, w.rect.height)
        if test0:
            actions.sleep("100ms")
            print(f'_win_move_pixels: after: {ui.active_window().rect=}')

def _win_size_pixels(w: ui.Window, direction:Direction, delta_width: int, delta_height: int) -> None:
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

def get_component_distances(w, direction, distance):
        # are we moving diagonally?
        direction_count = sum(direction.values())

        delta_width = delta_height = 0
        if direction_count  > 1:    # diagonal    
            #diagonal_length = math.sqrt(pow(w.rect.width - w.rect.x, 2) + pow(w.rect.height - w.rect.y, 2))
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
        
@mod.action_class
class Actions:
    # def win_move_absolute(x:int, y:int) -> None:
    #     "Move window to given absolute position"
    #     ui.active_window().move(x, y)

    # def win_move_relative(x:int, y:int) -> None:
    #     "Move window to given relative resize"
    #     w = ui.active_window()
    #     w.move(w.rect.x + x, w.rect.y + y)
    
    # def win_size_absolute(width:int, height:int) -> None:
    #     "size window to given absolute dimensions"
    #     ui.active_window().resize(width, height)

    # def win_size_relative(width:int, height:int) -> None:
    #     "size window to given relative dimensions"
    #     w = ui.active_window()
    #     w.resize(w.rect.width + width, w.rect.height + height)@mod.capture(rule="{self.letter}")

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

        delta_width, delta_height = get_component_distances(w, direction, distance)

        _win_move_pixels(w, direction, delta_width, delta_height)
    
    def win_move_percent(direction:Direction, percent:int) -> None:
        "move window some percentage of the current size"

        w = ui.active_window()

        delta_width = w.rect.width * (percent/100)
        delta_height = w.rect.height * (percent/100)

        _win_move_pixels(w, direction, delta_width, delta_height)  
    
    def win_size_pixels(direction:Direction, distance: int) -> None:
        "change window size by pixels"
        w = ui.active_window()
        
        delta_width, delta_height = get_component_distances(w, direction, distance)

        _win_size_pixels(w, direction, delta_width, delta_height)

    def win_size_percent(direction:Direction, percent:int) -> None:
        "change window size by a percentage of current size"
        
        w = ui.active_window()

        delta_width = w.rect.width * (percent/100)
        delta_height = w.rect.height * (percent/100)

        _win_size_pixels(w, direction, delta_width, delta_height)

    def win_snap_percent(percent: int) -> None:
        "change window size to some percentage of parent screen (in each direction)"

        direction = compass_direction(['all'])
        
        w = ui.active_window()

        delta_width = (w.screen.visible_rect.width * (percent/100)) - w.rect.width
        delta_height = (w.screen.visible_rect.height * (percent/100)) - w.rect.height
        
        _win_size_pixels(w, direction, delta_width, delta_height)