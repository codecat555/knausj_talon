
win test reset$:
    user.win_test_reset()

win move <user.compass_direction> <number> percent:
    user.win_move_percent(compass_direction, number)

win move <user.compass_direction> <number> pixels:
    user.win_move_pixels(compass_direction, number)

win stretch <user.compass_direction> <number> percent:
    user.win_size_percent(compass_direction, number)
    
win stretch <user.compass_direction> <number> pixels:
    user.win_size_pixels(compass_direction, number)

win shrink <user.compass_direction> <number> percent:
    user.win_size_percent(compass_direction, -1 * number)

win shrink <user.compass_direction> <number> pixels:
    user.win_size_pixels(compass_direction, -1 * number)

win snap <number> percent:
    user.win_snap_percent(number)