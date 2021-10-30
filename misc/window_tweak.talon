
win test reset$:
    user.win_test_reset()

win move <user.compass_direction> <number_small> percent:
    user.win_move_percent(compass_direction, number_small)

win move <user.compass_direction> <number_small> pixels:
    user.win_move_pixels(compass_direction, number_small)

win stretch <user.compass_direction> <number_small> percent:
    user.win_size_percent(compass_direction, number_small)
    
win stretch <user.compass_direction> <number_small> pixels:
    user.win_size_pixels(compass_direction, number_small)

win shrink <user.compass_direction> <number_small> percent:
    user.win_size_percent(compass_direction, -1 * number_small)

win shrink <user.compass_direction> <number_small> pixels:
    user.win_size_pixels(compass_direction, -1 * number_small)