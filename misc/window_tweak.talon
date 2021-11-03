# WIP - move compass_direction to last arg position uniformly
win move <user.compass_direction> <number> percent:
    user.win_move_percent(compass_direction, number)

win move <user.compass_direction> <number_signed> pixels:
    user.win_move_pixels(compass_direction, number_signed)

win move <number_signed> at <number_signed>:
    user.win_move_absolute(number_signed_1, number_signed_2)

win move <user.compass_direction> <number_signed> at <number_signed>:
    user.win_move_absolute(number_signed_1, number_signed_2, compass_direction)
    
win stretch <user.compass_direction> <number> percent:
    user.win_size_percent(compass_direction, -1 * number)
    
win stretch <user.compass_direction> <number> pixels:
    user.win_size_pixels(compass_direction, number)

win shrink <user.compass_direction> <number> percent:
    user.win_size_percent(compass_direction, -1 * number)

win shrink <user.compass_direction> <number> pixels:
    user.win_size_pixels(compass_direction, -1 * number)

win snap <number> percent:
    user.win_snap_percent(number)

win size <number> by <number>:
    user.win_size_absolute(number_1, number_2)

win size <user.compass_direction> <number> by <number>:
    user.win_size_absolute(number_1, number_2, compass_direction)

win revert:
    # WIP - win revert [size|position]
    user.win_revert()

win test reset$:
    user.win_test_reset()