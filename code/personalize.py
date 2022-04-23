# 
# this module provides a mechanism for overriding talon lists via a set of csv files located
# in a sub-folder of the settings folder - 'settings/list_personalization'.
# 
# CONTROL FILE
# ------------
# there is a master csv file called 'control.csv' which indicates how the other files should
# be used. It's format is:
#
#        action,talon list name,CSV file name
#
# The first field, action, may be ADD, DELETE, or REPLACE.
#
#     ADD - the CSV file entries should be added to the indicated list.
#  DELETE - the CSV file entries should be deleted from the indicated list.
# REPLACE - the indicated list should be completely replaced by the CSV file entries,
#           or by nothing if no CSV file is given.
#
# Note: the CSV file name field is optional for the REPLACE action, in which case the
# indicated list will simply be replaced with nothing.
#
#
# CSV FILE FORMAT - GENERAL
# -------------------------
# Nothing fancy, just basic comma-separated values. Commas in the data can be escaped
# using a backslash prefix.
#
#
# CSV FILE FORMAT - FOR DELETE ACTION
# -----------------------------------
# One item per line, indicating which keys should be removed from the given list.
#
#
# CSV FILE FORMAT - FOR ADD/REPLACE ACTIONS
# -----------------------------------------
# Two items per line, separated by a single comma. The first value is the key, and the
# second the value.

import os
import threading

from talon import Context, registry, app, Module, settings
from talon.scripting.types import CommandImpl
from talon.grammar import Grammar, Rule

from .user_settings import get_lines_from_csv, get_lines_from_csv_untracked

class PersonalValueError(ValueError):
    pass

mod = Module()

setting_enable_personalization = mod.setting(
    "enable_personalization",
    type=bool,
    default=False,
    desc="Whether to enable the personalizations defined by the CSV files in the settings folder.",
)

personalization_tag = mod.tag('personalization', desc='enable personalizations')

mod.list("test_list_replacement", desc="a list for testing the personalization replacement feature")

ctx = Context()
ctx.matches = r"""
tag: user.personalization
"""

ctx.lists["user.test_list_replacement"] = {'one': 'blue', 'two': 'red', 'three': 'green'}

# b,x = [(x[0],registry.contexts[x[1]]) for x in enumerate(registry.contexts)][152]
# y = [v for k,v in x.commands.items() if v.rule.rule == 'term user.word>'][0]


control_file_name = 'control.csv'

list_personalization_folder = 'list_personalization'
command_personalization_folder = 'command_personalization'

personal_list_control_file_name = os.path.join(list_personalization_folder, control_file_name)
personal_command_control_file_name = os.path.join(command_personalization_folder, control_file_name)

testing = True

class Personalizer():
    def __init__(self):
        self.mangle_map = self.MangleMap()
        self.personalization_mutex: threading.RLock = threading.RLock()

    def print_mangle_map(self: str) -> str:
        from pprint import pprint
        pprint(str(self.mangle_map))
    class MangleMap():

        def __init__(self):
            self.mangle_map = {
            ' ': '__'
            }
            self._populate_mangle_map()
            
        def __str__(self):
            return '\n'.join([f"'{k}'': '{v}'" for k,v in self.mangle_map.items()])

        def _populate_mangle_map(self):
            breakout = False
            command_count = 0
            contexts = list(registry.contexts.items())
            for context_path,context in contexts:
                
                commands = list(context.commands.items())
                fail_count = 0
                for mangle, command in commands:
                    
                    rule = command.rule
                    
                    # print(f'{context_path} - {len(mangle)}:{mangle=}, {len(rule.rule)}:{rule.rule=}')

                    new_mangle = self._parse_rule_into_map(rule, mangle)
                    # print(f'{rule_character} => {mangled_character}')

                    # new_mangle = '__' + ''.join([mangle_map[c] if c in self.mangle_map else c for c in rule]) + '__'
                    result = new_mangle == mangle
                    # print(f'Pass/Fail: {result}')
                    # print(f':\n\t{rule.rule}\n\t{mangle} ===>\n\t{new_mangle}')
                    if not result:
                        breakout = True
                        break
                    
                    command_count += 1       
                    if False and command_count >= 1:
                        breakout = True
                        break

                if breakout:
                    break
        
        def _parse_rule_into_map(self: str, rule: Rule, mangle: str) -> str:
            mangle_idx = 2
            # rule_idx = 0
            
            mangled = '__'

            if rule.anchor.startswith('^'):
                mangled += mangle[mangle_idx:mangle_idx+3]
                mangle_idx += 3

            for rule_character in rule.rule:
                # print(f'{mangle_idx=}')
                # rule_character = rule[rule_idx]

                # mangle_remainder = mangle[mangle_idx:]
                # print(f'remaining: {mangle_remainder}')
                
                mangled_character = rule_character
                if rule_character in self.mangle_map:
                    mangled_character = self.mangle_map[rule_character]
                    # mangle_val = '_' + str(hex(ord(character)))[2:]
                elif rule_character == '_' or rule_character != mangle[mangle_idx]:
                    mangled_character = mangle[mangle_idx:mangle_idx+3]
                    self.mangle_map[rule_character] = mangled_character

                # print(f"{rule_character} => {mangled_character}")
            
                mangled += mangled_character
                
                # rule_idx += 1
                mangle_idx += len(mangled_character)

                # if rule_idx > 20:
                #     breakout = True
            #     break

            if rule.anchor.endswith('$'):
                mangled += mangle[mangle_idx:mangle_idx+3]
            
            mangled += '__'

            return mangled

        def mangle_rule(self: str, command: CommandImpl) -> str:
            rule = command.rule.rule
            # print(f'{context_path}:: {len(mangle)}:{mangle=}, {len(rule)}:{rule=}')

            mangle_idx = 2
            # rule_idx = 0
            
            mangled = '__'

            if rule.anchor.startswith('^'):
                mangled += mangle[mangle_idx:mangle_idx+3]
                mangle_idx += 3

            for rule_character in rule:
            # while rule_idx < len(rule):
                # print(f'{rule_idx=}, {mangle_idx=}')
                # rule_character = rule[rule_idx]

                # mangle_remainder = mangle[mangle_idx:]
                # print(f'remaining: {mangle_remainder}')
                
                # mangled_character = mangle[mangle_idx]
                # mangle_incr = 1
                if rule_character in self.mangle_map:
                    mangled_character = self.mangle_map[rule_character]
                # elif build_map:
                #     # if rule_character == ' ':
                #     #     mangled_character = '__'
                #     # else:
                #     #     # capture the mapping for this character
                #     #     # mangle_val = '_' + str(hex(ord(character)))[2:]
                #     mangled_character = mangle[mangle_idx:mangle_idx+3]
                else:
                    raise ValueError(f'character not in mangle map: {rule_character}')

                # print(f"{rule_character} => {mangled_character}")
            
                if build_map:
                    self.mangle_map[rule_character] = mangled_character

                mangled += mangled_character
                
                # rule_idx += 1
                mangle_idx += len(mangled_character)

                # if rule_idx > 20:
                #     breakout = True
            #     break
            
            if rule.anchor.endswith('$'):
                mangled += mangle[mangle_idx:mangle_idx+3]
            
            mangled += '__'

            return mangled

    def tag_context_match(self, context: Context) -> str:
        new_match_string: str = ''
        # tag_expression = f'tag: user.{personalization_tag}\n'
        # tag_expression = f'tag: user.{personalization_tag}\n'
        tag_expression = f'tag: user.personalization\n'
        and_tag_expression = 'and ' + tag_expression

        old_match_string = context.matches
        print(f'{context.path=}, {old_match_string=}')
        if len(new_match_string) == 0:
            new_match_string = tag_expression
        else:
            # continuing = True
            # for line in old_match_string.split('\n'):
            #     if not len(line):
            #         continue
                
            #     expression = ''
            #     while continuing:
            #         expression += line
            #         # check special cases
            #         for left, right in (l.strip(), r.strip() for l,r in line.split(':')):
            #             print(f'{left=}, {right=}')
            saw_and = False
            current_claws = []
            for line in old_match_string.split('\n'):
                if not len(line):
                    continue
                
                if len(current_claws) == 0:
                    # always push the first line of a clause before considering 'and'
                    current_claws.append(line)
                else:
                    if line.strip().startswith(' and'):
                        saw_and = True

                    if saw_and:
                        # keep pushing lines until we detect the end of the clause
                        current_claws.append(line)

                saw_and = line.strip().endswith(' and')
                    
                if not saw_and:
                    # found end of claws, add the tag
                    current_claws.append(and_tag_expression)

                    # add the new clause
                    new_match_string += ''.join(current_claws)
                    
                    # start a new clause
                    current_claws = []
                    saw_and = False

                # expression = ''
                # while saw_and:
                #     expression += line
                #     # check special cases
                #     for left, right in (l.strip(), r.strip() for l,r in line.split(':')):
                #         print(f'{left=}, {right=}')
                        
                
        print(f'{old_match_string=}, {new_match_string=}')
        
        return new_match_string
        
    def load_personalization(self):
        if not settings.get('user.enable_personalization'):
            return

        # this code has multiple event triggers which may overlap. it's not clear how talon
        # handles that case, so use a mutex here to make sure only one copy runs at a time.
        #
        # note: this mutex may not actually be needed, I put it in because I was multiple simultaneous
        # invocations of this code, which seem to be due to https://github.com/talonvoice/talon/issues/451.
        with self.personalization_mutex:
            self.load_list_personalizations()
            self.load_command_personalizations()

    def load_list_personalizations(self):
        print(f'load_list_personalizations.py - on_ready(): loading customizations from "{personal_list_control_file_name}"...')
        
        try:
            line_number = 0
            for action, target, *remainder in get_lines_from_csv(personal_list_control_file_name):
                line_number += 1

                if testing:
                    print(f'{personal_list_control_file_name}, at line {line_number} - {target, action, remainder}')
                    # print(f'{personalize_file_name}, at line {line_number} - {target in ctx.lists=}')
                    pass

                if not target in registry.lists:
                    print(f'{personal_list_control_file_name}, at line {line_number} - cannot redefine a list that does not exist, skipping: {target}')
                    continue

                file_name = None
                if len(remainder):
                    file_name = os.path.join(list_personalization_folder, remainder[0])
                elif action.upper() != 'REPLACE':
                    print(f'{personal_list_control_file_name}, at line {line_number} - missing file name for add or delete entry, skipping: {target}')
                    continue

                if target in ctx.lists.keys():
                    source = ctx.lists[target]
                else:
                    source = registry.lists[target][0]
                        
                value = {}
                if action.upper() == 'DELETE':
                    deletions = []
                    try:
                        for row in get_lines_from_csv(file_name):
                            if len(row) > 1:
                                print(f'{personal_list_control_file_name}, at line {line_number} - files containing deletions must have just one value per line, skipping entire file: {file_name}')
                                raise PersonalValueError()
                            deletions.append(row[0])
                    except FileNotFoundError:
                        print(f'{personal_list_control_file_name}, at line {line_number} - missing file for delete entry, skipping: {file_name}')
                        continue

                    # print(f'personalize_file_name - {deletions=}')

                    value = source.copy()
                    value = { k:v for k,v in source.items() if k not in deletions }

                elif action.upper() == 'ADD' or action.upper() == 'REPLACE':
                    additions = {}
                    if file_name:  # some REPLACE entries may not have filenames, and that's okay
                        try:
                            for row in get_lines_from_csv(file_name):
                                if len(row) != 2:
                                    print(f'{personal_list_control_file_name}, at line {line_number} - files containing additions must have just two values per line, skipping entire file: {file_name}')
                                    raise PersonalValueError()
                                additions[ row[0] ] = row[1]
                        except FileNotFoundError:
                            print(f'{personal_list_control_file_name}, at line {line_number} - missing file for add or replace entry, skipping: {file_name}')
                            continue
                    
                    if action.upper() == 'ADD':
                        value = source.copy()
                        
                    value.update(additions)
                else:
                    print(f'{personal_list_control_file_name}, at line {line_number} - unknown action, skipping: {action}')
                    continue
                    
                # print(f'personalize_file_name - after {action.upper()}, {value=}')

                # do it to it
                ctx.lists[target] = value

        except FileNotFoundError as e:
            # below check is necessary because the inner try blocks above do not catch this
            # error completely...something's odd about the way talon is handling these exceptions.
            if os.path.basename(e.filename) == personal_list_control_file_name:
                print(f'Setting  "{setting_enable_personalization.path}" is enabled, but personalization control file does not exist: {personal_list_control_file_name}')
        except PersonalValueError:
            # nothing to do
            pass

    command_add_disallowed_title = "Talon - ADD not allowed for commands"
    command_add_disallowed_notice = 'Command personalization: to add new commands, use a .talon file.'
    def load_command_personalizations(self):
        #
        # 1. fetch or create target context
        #   1. fetch target context, if it exists
        #   2. create target context
        #        1. fetch source context
        #        2. parse source context matches into segments
        #        3. add personalization tag to each segment
        #        4. create new context with new matches
        # 
        # 2. create a Rule (<class 'talon.grammar.rule.Rule'>) with new command text
        #   1. pass in new context as 'ref'
        #
        # 3. create CommandImpl(Rule)
        #
        # 4. create mangle from rule
        #
        # 5. add new CommandImpl to context.commands with key mangle
        #

        print(f'load_command_personalizations(): loading customizations from "{personal_command_control_file_name}"...')
        
        send_add_notification = False
        try:
            line_number = 0
            # for action, target, file_name in get_lines_from_csv(personal_command_control_file_name):
            for action, target, file_name in get_lines_from_csv_untracked(personal_command_control_file_name):
                line_number += 1

                if testing:
                    # print(f'{personal_command_control_file_name}, at line {line_number} - {target, action, remainder}')
                    print(f'{personal_command_control_file_name}, at line {line_number} - {target, action, file_name}')
                    # print(f'{personalize_file_name}, at line {line_number} - {target in ctx.lists=}')
                    pass

                if not target in registry.contexts:
                    print(f'{personal_command_control_file_name}, at line {line_number} - cannot _ commands in a context that does not exist, skipping: {target}')
                    continue

                file_path = os.path.join(command_personalization_folder, file_name)

    # WIP - not sure about this bit
                # if target in ctx.lists.keys():
                #     source = ctx.lists[target]
                # else:
                #     source = registry.lists[target][0]
                context = registry.contexts[target]

                tagged_context = self.tag_context_match(context)
                print(f'load_command_personalizations: {tagged_context=}')

                # # commands = {x.rule.rule: x for x in context.commands.values()}
                # command_dict = {x:mangle for mangle,x in context.commands.items()}
                        
                # value = {}
                # if action.upper() == 'DELETE':
                #     deletions = []
                #     try:
                #         for row in get_lines_from_csv(file_path):
                #             if len(row) > 1:
                #                 print(f'{personal_command_control_file_name}, at line {line_number} - files containing deletions must have just one value per line, skipping entire file: {file_path}')
                #                 raise PersonalValueError()
                #             deletions.append(row[0])
                #     except FileNotFoundError:
                #         print(f'{personal_command_control_file_name}, at line {line_number} - missing file for delete entry, skipping: {file_path}')
                #         continue

                #     # print(f'personalize_file_name - {deletions=}')
                #     value = { k: 'skip()' for k in commands.keys() if k in deletions }
                    
                # elif action.upper() == 'REPLACE':
                #     additions = {}
                #     try:
                #         for row in get_lines_from_csv(file_path):
                #             if len(row) != 2:
                #                 print(f'{personal_command_control_file_name}, at line {line_number} - files containing replacements must have just two values per line, skipping entire file: {file_path}')
                #                 raise PersonalValueError()
                #             additions[ row[0] ] = row[1]
                #     except FileNotFoundError:
                #         print(f'{personal_command_control_file_name}, at line {line_number} - missing file for add or replace entry, skipping: {file_path}')
                #         continue
                        
                #     commands.update(additions)
                # else:
                #     if action.upper() == 'ADD':
                #         send_add_notification = True
                        
                #     print(f'{personal_command_control_file_name}, at line {line_number} - unknown action, skipping: {action}')
                #     continue
                    
                # # print(f'personalize_file_name - after {action.upper()}, {value=}')

                # # do it to it
                # registry.contexts[target] = value

                # break

        except FileNotFoundError as e:
            # below check is necessary because the inner try blocks above do not catch this
            # error completely...something's odd about the way talon is handling these exceptions.
            print(f'personalize_file_name - {e.filename}')
            if os.path.basename(e.filename) == personal_command_control_file_name:
                print(f'Setting  "{setting_enable_personalization.path}" is enabled, but personalization control file does not exist: {personal_command_control_file_name}')
        except PersonalValueError:
            # nothing to do
            pass

        if send_add_notification:
            app.notify(
                title=command_add_disallowed_title,
                body=command_add_disallowed_notice
            )

def on_ready():
    p.load_personalization()
    # p.print_mangle_map()

    # catch updates
    settings.register("", refresh_settings)
    
def refresh_settings(setting_path, new_value):
        # print(f'refresh_settings() - {setting_path=}, {new_value=}')
        if setting_path == setting_enable_personalization.path:
            p.load_personalization()

p = Personalizer()

app.register("ready", on_ready)
