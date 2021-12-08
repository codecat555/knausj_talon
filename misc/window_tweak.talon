
win show$:
    user.win_show()

win hide$:
    user.win_hide()

win move$:
    user.win_move()

win move <user.compass_direction>$:
    user.win_move(compass_direction)

win move <user.compass_direction> <number> percent$:
    user.win_move_percent(number, compass_direction)

win move <user.compass_direction> <number_signed> pixels$:
    user.win_move_pixels(number_signed, compass_direction)

win move <number_signed> at <number_signed>$:
    user.win_move_absolute(number_signed_1, number_signed_2)

# For this command, compass_direction indicates which part of the window
# should be moved to the given coordinate. Northwest means the top left
# corner, east means the midpoint of the right-hand edge - like that.
win move <user.compass_direction> <number_signed> at <number_signed>$:
    user.win_move_absolute(number_signed_1, number_signed_2, compass_direction)

win stretch$:
    user.win_stretch()

win stretch <user.compass_direction>$:
    user.win_stretch(compass_direction)

win stretch <user.compass_direction> <number> percent$:
    user.win_resize_percent(number, compass_direction)

win stretch <user.compass_direction> <number> pixels$:
    user.win_resize_pixels(number, compass_direction)

win shrink$:
    user.win_shrink()

win shrink <user.compass_direction>$:
    user.win_shrink(compass_direction)

win shrink <user.compass_direction> <number> percent$:
    user.win_resize_percent(-1 * number, compass_direction)

win shrink <user.compass_direction> <number> pixels$:
    user.win_resize_pixels(-1 * number, compass_direction)

win snap <number> percent [of screen]$:
    user.win_snap_percent(number)

win size <number> by <number>$:
    user.win_resize_absolute(number_1, number_2)

# for this command, the direction indicates which part of the window should
# remain anchored while the other dimensions adust to reach the new size.
win size <user.compass_direction> <number> by <number>$:
    user.win_resize_absolute(number_1, number_2, compass_direction)

win revert$:
    user.win_revert()
