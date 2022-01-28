#(jay son | jason ): "json"
#(http | htp): "http"
#tls: "tls"
#M D five: "md5"
#word (regex | rejex): "regex"
#word queue: "queue"
#word eye: "eye"
#word iter: "iter"
#word no: "NULL"
#word cmd: "cmd"
#word dup: "dup"
#word shell: "shell".
zoom in: edit.zoom_in()
zoom out: edit.zoom_out()
zoom reset: edit.zoom_reset()
scroll up: edit.page_up()
scroll down: edit.page_down()
copy that: edit.copy()
cut that: edit.cut()
paste that: edit.paste()
undo [that]: edit.undo()
redo [that]: edit.redo()
paste match: edit.paste_match_style()
file save: edit.save()
wipe: key(backspace)    
(pad | padding): 
	insert("  ") 
	key(left)
slap: edit.line_insert_down()

# from pokey - update additional_words.csv using vscode.
additional word:
    user.switcher_focus("Code")
    user.vscode("workbench.action.openRecent")
    sleep(50ms)
    insert("knausj_talon")
    key(enter)
    sleep(250ms)
    user.vscode("workbench.action.quickOpen")
    sleep(200ms)
    insert("additional_words")
    sleep(300ms)
    key(enter)
    sleep(200ms)
    edit.file_end()
    edit.line_insert_down()

additional brief:
    user.switcher_focus("Code")
    user.vscode("workbench.action.openRecent")
    sleep(50ms)
    insert("knausj_talon")
    key(enter)
    sleep(250ms)
    user.vscode("workbench.action.quickOpen")
    sleep(200ms)
    insert("code/abbreviate")
    sleep(300ms)
    key(enter)
    sleep(200ms)
    edit.file_end()
    edit.line_insert_down()
    
additional phone:
    user.switcher_focus("Code")
    user.vscode("workbench.action.openRecent")
    sleep(50ms)
    insert("knausj_talon")
    key(enter)
    sleep(250ms)
    user.vscode("workbench.action.quickOpen")
    sleep(200ms)
    insert("homophones.csv")
    sleep(300ms)
    key(enter)
    sleep(200ms)
    edit.file_end()
    edit.line_insert_down()