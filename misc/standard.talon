zoom in: edit.zoom_in()
zoom out: edit.zoom_out()
zoom reset: edit.zoom_reset()
scroll up: edit.page_up()
scroll down: edit.page_down()
copy that: edit.copy()
cut that: edit.cut()
(pace | paste) that: edit.paste()
(pace | paste) enter:
  edit.paste()
  key(enter)
nope: edit.undo()
redo [that]: edit.redo()
paste match: edit.paste_match_style()
(file save|disk): edit.save()
(file save|disk) all: edit.save_all()
wipe: key(backspace)    
(pad | padding): user.insert_between(" ", " ")
slap: edit.line_insert_down()

additional word:
    user.edit_additional_words()

additional replacement:
    user.edit_words_to_replace()

additional brief:
    user.edit_abbreviations()

additional phone:
    user.edit_homophones()
