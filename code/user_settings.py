import csv
import os
from pathlib import Path
from typing import Dict, List, Tuple
from talon import resource

# NOTE: This method requires this module to be one folder below the top-level
#   knausj folder.
SETTINGS_DIR = Path(__file__).parents[1] / "settings"

if not SETTINGS_DIR.is_dir():
    os.mkdir(SETTINGS_DIR)


def get_list_from_csv(
    filename: str, headers: Tuple[str, str], default: Dict[str, str] = {}
):
    """Retrieves list from CSV"""
    path = SETTINGS_DIR / filename
    assert filename.endswith(".csv")

    if not path.is_file():
        with open(path, "w", encoding="utf-8", newline="") as file:
            writer = csv.writer(file)
            writer.writerow(headers)
            for key, value in default.items():
                writer.writerow([key] if key == value else [value, key])

    # Now read via resource to take advantage of talon's
    # ability to reload this script for us when the resource changes
    with resource.open(str(path), "r") as f:
        rows = list(csv.reader(f))

    # print(str(rows))
    mapping = {}
    if len(rows) >= 2:
        actual_headers = rows[0]
        if not actual_headers == list(headers):
            print(
                f'"{filename}": Malformed headers - {actual_headers}.'
                + f" Should be {list(headers)}. Ignoring row."
            )
        for row in rows[1:]:
            if len(row) == 0:
                # Windows newlines are sometimes read as empty rows. :champagne:
                continue
            if len(row) == 1:
                output = spoken_form = row[0]
            else:
                output, spoken_form = row[:2]
                if len(row) > 2:
                    print(
                        f'"{filename}": More than two values in row: {row}.'
                        + " Ignoring the extras."
                    )
            # Leading/trailing whitespace in spoken form can prevent recognition.
            spoken_form = spoken_form.strip()
            mapping[spoken_form] = output

    return mapping

def get_lines_from_csv(filename: str, escapechar='\\'):
    """Retrieves contents of CSV file in settings dir"""
    path = SETTINGS_DIR / filename
    assert filename.endswith(".csv")

    # read via resource to take advantage of talon's
    # ability to reload this script for us when the resource changes
    rows = []
    with resource.open(str(path), "r") as f:
        # this is an option that I abandoned when I hit https://github.com/talonvoice/talon/issues/451,
        # seems best to keep things simpler for now.
        # for row in csv.reader(f, escapechar=escapechar):
        #     yield row
        rows = list(csv.reader(f, escapechar=escapechar))

    return rows

# added this while debugging an issue that turned out to be https://github.com/talonvoice/talon/issues/451.
def get_lines_from_csv_untracked(filename: str, escapechar='\\'):
    """Retrieves contents of CSV file in settings dir, without tracking"""
    path = SETTINGS_DIR / filename
    assert filename.endswith(".csv")

    # read via resource to take advantage of talon's
    # ability to reload this script for us when the resource changes
    rows = []
    with open(str(path), "r") as f:
        rows = list(csv.reader(f, escapechar=escapechar))

    print(f'returning {rows}')
    return rows

