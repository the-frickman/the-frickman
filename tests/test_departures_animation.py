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
                board.build(current, checked + timedelta(minutes=10))
                self.assertEqual(path.read_bytes(), rendered)

        root = ElementTree.fromstring(rendered)
        self.assertEqual(json.loads(root.find("{*}metadata").text)["checked"], saved["checked"])
        cells = iter(root.find("{*}g[@data-row='0']"))
        for old, new, (_, width) in zip(previous[0], current[0], board.COLUMNS):
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
