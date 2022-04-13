question [mark]: "?"
(downscore | underscore): "_"
double dash: "--"
(bracket | brack | left bracket): "{"
(rbrack | are bracket | right bracket): "}"
triple quote: "'''"
(triple grave | triple back tick | gravy):
    insert("```")
(dot dot | dotdot): ".."
ellipses: "..."
(comma and | spamma): ", "
plus: "+"
arrow: "->"
dub arrow: "=>"
new line: "\\n"
carriage return: "\\r"
line feed: "\\r\\n"
empty dubstring:
    '""'
    key(left)
empty escaped (dubstring|dub quotes):
    '\\"\\"'
    key(left)
    key(left)
empty string:
    "''"
    key(left)
empty escaped string:
    "\\'\\'"
    key(left)
    key(left)
(inside parens | args) | round pair:
	insert("()")
	key(left)
inside (squares | square brackets | list) | square pair:
	insert("[]")
	key(left)
inside (bracket | braces ) | curly pair:
	insert("{}")
	key(left)
inside percent:
	insert("%%")
	key(left)
inside (quotes | string ) | string pair:
	insert("''")
	key(left)
inside (double quotes | dubquotes ) | dub pair:
    insert('""')
	key(left)
inside (graves | back ticks):
	insert("``")
	key(left)
inside (angles) | angle pair:
	insert("<>")
	key(left)
# should simplify these down to a single word pattern for each
angle that:
    text = edit.selected_text()
    user.paste("<{text}>")
(square | square bracket) that:
    text = edit.selected_text()
    user.paste("[{text}]")
(bracket | brace | curl) that:
    text = edit.selected_text()
    user.paste("{{{text}}}")
(parens | args | round) that:
    text = edit.selected_text()
    user.paste("({text})")
percent that:
    text = edit.selected_text()
    user.paste("%{text}%")
quote that:
    text = edit.selected_text()
    user.paste("'{text}'")
(double quote | dubquote) that:
    text = edit.selected_text()
    user.paste('"{text}"')
(grave | back tick) that:
    text = edit.selected_text()
    user.paste('`{text}`')
