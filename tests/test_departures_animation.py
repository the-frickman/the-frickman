import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from xml.etree import ElementTree

from scripts import build_departures as board


class DeparturesAnimationTest(unittest.TestCase):
    def test_remark_only_update_still_opens_every_populated_column(self):
        fields = ["LX  092", "BUENOS AIRES", "GRU", "22:35", "22:45", "E", "1",
                  "121-126", "E23", "BOARDING"]
        previous = [fields, *[board.EMPTY] * 4]
        current = [[*fields[:-1], "CLOSED"], *previous[1:]]
        checked = datetime(2026, 11, 17, 21, 30, tzinfo=timezone.utc)
        # This is the metadata written by the original, delta-only renderer.
        saved = {"rows": current, "before": previous, "checked": checked.isoformat()}
        shell = board.BOARD.read_text().partition(board.MARKER)[0]
        with TemporaryDirectory() as directory:
            path = Path(directory) / "board.svg"
            path.write_text(shell + board.MARKER + '<metadata id="snapshot">'
                            + json.dumps(saved) + '</metadata></svg>')
            with patch.object(board, "BOARD", path):
                board.build(current, checked + timedelta(minutes=5))
                rendered = path.read_bytes()
                mobile_path = path.with_name("splitflap-board-mobile.svg")
                portrait = mobile_path.read_bytes()
                mobile_path.unlink()  # Repair the companion asset even on an unchanged poll.
                board.build(current, checked + timedelta(minutes=10))
                self.assertEqual(path.read_bytes(), rendered)
                self.assertEqual(mobile_path.read_bytes(), portrait)

        root = ElementTree.fromstring(rendered)
        self.assertEqual(json.loads(root.find("{*}metadata").text)["checked"], saved["checked"])
        mobile = ElementTree.fromstring(portrait)
        self.assertEqual(mobile.find("{*}metadata").text, root.find("{*}metadata").text)
        self.assertGreater(int(mobile.get("height")), int(mobile.get("width")))
        for desktop_row, mobile_row in zip(root.findall("{*}g[@data-row]"), mobile.findall("{*}g[@data-row]"), strict=True):
            self.assertEqual(desktop_row.get("aria-label"), mobile_row.get("aria-label"))
            for wide, narrow in zip(desktop_row, mobile_row, strict=True):
                self.assertNotEqual(wide.get("transform"), narrow.get("transform"))
                self.assertEqual([el.attrib for el in wide.iter()][1:], [el.attrib for el in narrow.iter()][1:])
        cells = iter(root.find("{*}g[@data-row='0']"))
        for field, (old, new, (_, width)) in enumerate(zip(previous[0], current[0], board.COLUMNS)):
            for first, final in zip(old.ljust(width), new.ljust(width)):
                cell = next(cells)
                tracks = cell.findall(".//{*}defs/{*}use/{*}animate")
                if first == final == " ":
                    self.assertFalse(tracks)
                    continue
                self.assertEqual(len(tracks), 2)
                for track in tracks:
                    times = [float(t) * board.CYCLE for t in track.get("keyTimes").split(";")]
                    faces = track.get("values").split(";")
                    self.assertEqual(faces[0], board.ref(" "))
                    self.assertEqual([face for t, face in zip(times, faces) if t < board.UPDATE - board.STEP / 2][-1],
                                     board.ref(first))
                    self.assertEqual(faces[-1], board.ref(final))
                    if field in (1, 2) and first.isalpha():
                        for symbol in "9*:-./":
                            self.assertIn(board.ref(symbol), faces[:faces.index(board.ref(first))])
                    elif field in (3, 4):
                        self.assertNotIn(board.ref("*"), faces)
