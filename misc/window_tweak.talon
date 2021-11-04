

win move <user.compass_direction> <number> percent:
    user.win_move_percent(number, compass_direction)

win move <user.compass_direction> <number_signed> pixels:
    user.win_move_pixels(number_signed, compass_direction)

win move <number_signed> at <number_signed>:
    user.win_move_absolute(number_signed_1, number_signed_2)
0
win move <user.compass_direction> <number_signed> at <number_signed>:
    user.win_move_absolute(number_signed_1, number_signed_2, compass_direction)
    
win stretch <user.compass_direction> <number> percent:
    user.win_size_percent(-1 * number, compass_direction)
    
win stretch <user.compass_direction> <number> pixels:
    user.win_size_pixels(number, compass_direction)

win shrink <user.compass_direction> <number> percent:
    user.win_size_percent(-1 * number, compass_direction)

win shrink <user.compass_direction> <number> pixels:
    user.win_size_pixels(-1 * number, compass_direction)

win snap <number> percent:
    user.win_snap_percent(number)

win size <number> by <number>:
    user.win_size_absolute(number_1, number_2)

win size <user.compass_direction> <number> by <number>:
    user.win_size_absolute(number_1, number_2, compass_direction)

win revert:
    # WIP - win revert [size|position]
    user.win_revert()
