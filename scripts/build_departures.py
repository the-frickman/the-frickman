"""Generate a self-contained split-flap snapshot from Zürich Airport's public feed."""

import json
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path
from string import ascii_uppercase, digits
from urllib.request import urlopen
from xml.etree import ElementTree
from xml.sax.saxutils import escape
from zoneinfo import ZoneInfo

BOARD = Path(__file__).resolve().parents[1] / "assets" / "splitflap-board.svg"
FEED = "https://flightdata.flughafen-zuerich.ch/flights"
ZURICH = ZoneInfo("Europe/Zurich")
MARKER = "  <!-- BEGIN GENERATED DEPARTURES -->"
COLUMNS = ((51, 7), (222, 13), (518, 3), (597, 5), (719, 5),
           (848, 1), (910, 1), (1008, 7), (1177, 3), (1260, 10))
EMPTY = [""] * len(COLUMNS)
STEP = 1 / (16 * 0.60)
# Start both movements on a motor tick. The longest drum has 42 faces.
OPENING = 2 * STEP
UPDATE = 56 * STEP
CYCLE = 11  # Hold the current flight data after both movements have finished.
ATTENTION = {"BOARDING", "GO TO GATE", "GATE OPEN", "FINAL CALL", "LAST CALL"}


def timestamp(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None


def lettering(value):
    letters = unicodedata.normalize("NFKD", str(value or "").upper())
    return re.sub(r"[^ A-Z0-9*./:-]", "", letters)


def next_departures(feed, now):
    airports = {f.get("airportName"): f["PDS"] for f in feed
                if f.get("airportName") and re.fullmatch("[A-Z]{3}", f.get("PDS") or "")}
    upcoming = []
    for f in feed:
        if f.get("flightType") != "D" or not f.get("isCommercial") or f.get("ATD"):
            continue
        status = lettering(f.get("statusTextEn"))
        if status in {"DEPARTED", "CANCELLED", "CANCELED", "ROLLING", "AIRBORNE"}:
            continue
        scheduled, estimated = timestamp(f.get("STD")), timestamp(f.get("ETD"))
        due = estimated or scheduled
        grace = timedelta(minutes=20) if status in ATTENTION or status == "CLOSED" else timedelta()
        if not scheduled or not now - grace <= due < now + timedelta(days=1):
            continue
        carrier, number = lettering(f.get("FLC")), lettering(f.get("FLN"))
        if not carrier or not number:
            continue
        city = lettering(f.get("cityEn"))
        if len(city) > 13 or not city:
            city = lettering(f.get("PDS")) or city[:13]
        gate = lettering(f.get("GAT"))
        # The airport announces when a gate will be published before calling passengers.
        if status.startswith("GATE INFO AT "):
            remark = "INFO " + status[-5:]
            gate = ""
        else:
            remark = status or "SCHEDULED"
        values = [f"{carrier} {number:>4}", city, airports.get(f.get("viaAirportName"), ""),
                  scheduled.astimezone(ZURICH).strftime("%H:%M"),
                  estimated.astimezone(ZURICH).strftime("%H:%M") if estimated else "",
                  gate[:1] if gate[:1].isalpha() else "", lettering(f.get("CAM")), "",
                  gate, remark]
        upcoming.append((due, scheduled, carrier, number, values))
    rows, seen = [], set()
    for _, scheduled, carrier, number, values in sorted(upcoming):
        key = (scheduled, carrier, number)
        if key not in seen:
            rows.append([v[:width] for v, (_, width) in zip(values, COLUMNS)])
            seen.add(key)
        if len(rows) == 5:
            break
    if not rows:
        raise ValueError("No upcoming commercial departures in feed. Keeping last snapshot.")
    return rows + [EMPTY] * (5 - len(rows))


def ref(char):
    return "#g" + {" ": "_", ":": "c", "*": "star", "/": "slash", ".": "dot"}.get(char, char)


def discrete(attribute, events):
    """Hold each face until the next key, then leave the final face visible."""
    times = ";".join(f"{time / CYCLE:.6f}".rstrip("0").rstrip(".") for time, _ in events)
    values = ";".join(str(value) for _, value in events)
    return (f'<animate attributeName="{attribute}" calcMode="discrete" dur="{CYCLE}s" '
            f'keyTimes="{times}" values="{values}" fill="freeze"/>')


def print_track(name, events):
    return f'<use id="{name}" href="{events[-1][1]}">{discrete("href", events)}</use>'


def motor(tile_id, x, row, first, goal, stops, *, place_name):
    """A released card exposes the next top and turns into the next bottom."""
    if first == goal == " ":
        return ""
    alphabet = " " + ascii_uppercase + digits + "*-./:"
    opening = OPENING
    if place_name:
        # The Frankfurt close-up shows numerals, an asterisk and punctuation
        # passing through destination cells as their drums seek the next name.
        alphabet = " " + digits + "*:-./" + ascii_uppercase
        opening += ((x + 3 * row) % 9) * STEP
    elif {first, goal} <= set(digits + " :"):
        alphabet = " " + digits + (":" if ":" in (first, goal) else "")

    phase = ((x + 3 * row) % 7) * STEP / 12
    top = [(0, ref(" "))]
    bottom = [(0, ref(" "))]
    moving = [(0, 0)]
    index = 0
    for change, target in ((OPENING, first), (UPDATE, goal)):
        target_index = alphabet.index(target)
        count = (target_index - index) % len(alphabet)
        if not count:
            continue
        start = (opening if change == OPENING else change) + phase
        stop = start + STEP * count
        stops[change] = max(stops.get(change, 0), stop)
        moving.extend(((start, 1), (stop, 0)))
        for step in range(count):
            exposed = ref(alphabet[(index + step + 1) % len(alphabet)])
            top.append((start + step * STEP, exposed))
            bottom.append((start + (step + 1) * STEP, exposed))
        index = target_index
    for events in (top, bottom, moving):
        events.append((CYCLE, events[-1][1]))
    a, b = tile_id + "t", tile_id + "b"
    return f'''<g class="rest-face"><use href="{ref(goal)}"/></g>
<g class="animated-face">
  <defs>{print_track(a, top)}{print_track(b, bottom)}</defs>
  <g clip-path="url(#top-clip)"><use href="#{a}"/></g>
  <g clip-path="url(#bottom-clip)"><use href="#{b}"/></g>
  <g opacity="0">{discrete("opacity", moving)}
    <g transform="translate(0 30)"><g>
      <animateTransform attributeName="transform" type="scale" dur="{STEP}s" begin="{phase:.6f}s" end="{stop:.6f}s" repeatCount="indefinite"
        keyTimes="0;.20;.38;.55;.68;.8;1" values="1 1;1 .98;1 .77;1 0;1 -.65;1 -1;1 -1"/>
      <g transform="translate(0 -30)">
        <g clip-path="url(#top-clip)">
          <animate attributeName="opacity" calcMode="discrete" begin="{phase:.6f}s" dur="{STEP}s" end="{stop:.6f}s" repeatCount="indefinite" keyTimes="0;.55;1" values="1;0;0"/>
          <use href="#upper"/><use href="#{b}"/>
        </g>
        <g transform="translate(0 60) scale(1 -1)" clip-path="url(#bottom-clip)" opacity="0">
          <animate attributeName="opacity" calcMode="discrete" begin="{phase:.6f}s" dur="{STEP}s" end="{stop:.6f}s" repeatCount="indefinite" keyTimes="0;.55;1" values="0;1;1"/>
          <use href="#lower"/><use href="#{a}"/>
        </g>
      </g>
    </g></g>
  </g>
</g>'''


def build_desktop(rows, now):
    old_svg = BOARD.read_text()
    shell, marker, _ = old_svg.partition(MARKER)
    if not marker:
        raise ValueError("SVG artwork is missing its departures marker")
    saved = ElementTree.fromstring(old_svg).find("{*}metadata[@id='snapshot']")
    previous = rows
    if saved is not None:
        state = json.loads(saved.text)
        last_change = timestamp(state["checked"])
        if rows == state["rows"] and now.astimezone(ZURICH).date() == last_change.astimezone(ZURICH).date():
            if state.get("drum_revision") == 2:
                return
            # Upgrade the existing SVG even when the airport data hasn't changed.
            previous = state["before"] if any(any(row) for row in state["before"]) else rows
            now = last_change
        elif timedelta(0) <= now - last_change <= timedelta(minutes=45):
            previous = state["rows"]
    state = {"before": previous, "rows": rows, "checked": now.isoformat(), "drum_revision": 2}
    stamp = now.astimezone(ZURICH).strftime("%d %b %Y · %H:%M %Z").upper()
    parts = [shell.rstrip(), MARKER, f'<metadata id="snapshot">{escape(json.dumps(state))}</metadata>',
             f'<text x="755" y="57" text-anchor="middle" fill="#c9c7bb" '
             f'font-family="monospace" font-size="18">BOARD UPDATED · {stamp}</text>']
    for row, (old, new) in enumerate(zip(previous, rows)):
        stops = {}
        label = escape(" · ".join(filter(None, new)))
        parts.append(f'<g data-row="{row}" aria-label="{label}" fill="#f8f5e9" '
                     f'transform="translate(0 {143 + 43*row}) scale(1 .68)">')
        for field, (x, width) in enumerate(COLUMNS):
            for i, (before, after) in enumerate(zip(old[field].ljust(width), new[field].ljust(width))):
                pos = x + 22*i
                face = motor(f"r{row}x{pos}", pos, row, before, after, stops, place_name=field in (1, 2))
                parts.append(f'<g transform="translate({pos} 0)"><use href="#tile"/>'
                             f'{face}<use href="#seam"/></g>')
        parts.append(f'</g><g transform="translate(27 {163.4 + 43*row:.1f})"><use href="#dark-pair"/>')
        if new[-1] in ATTENTION:
            parts.append('<use class="rest-face" href="#attention-pair"/>')
        if old[-1] in ATTENTION or new[-1] in ATTENTION:
            lamp_events = [(0, 0)]
            for change, status in ((OPENING, old[-1]), (UPDATE, new[-1])):
                if change in stops:
                    lamp_events.extend(((change, 0), (stops[change], int(status in ATTENTION))))
            parts.append(f'<g class="motion-lamps" opacity="{int(new[-1] in ATTENTION)}">'
                         f'{discrete("opacity", lamp_events)}<use href="#attention-pair"/></g>')
        parts.append("</g>")
    parts.append("</svg>\n")
    BOARD.write_text("\n".join(parts))


# Each tuple positions the same desktop field in one of two lines per flight.
MOBILE_FIELDS = (
    ("Flight", 45, 0), ("Destination", 215, 0), ("Via", 26, 76),
    ("Scheduled", 518, 0), ("Estimate", 109, 76), ("Pier", 232, 76),
    ("Area", 281, 76), ("Counter", 334, 76), ("Gate", 648, 0),
    ("Remarks", 500, 76),
)


def build_mobile():
    """Reposition the published cells so both images share every face and motor tick."""
    svg = "http://www.w3.org/2000/svg"
    ElementTree.register_namespace("", svg)
    ElementTree.register_namespace("xlink", "http://www.w3.org/1999/xlink")
    root = ElementTree.parse(BOARD).getroot()
    root.attrib.update(width="736", height="1008", viewBox="0 0 736 1008")
    defs = root.find("{*}defs")
    snapshot = root.find("{*}metadata")
    # Keep the common artwork and motors. Replace the wide bezel and headings.
    children = list(root)
    for node in children[children.index(defs) + 1:children.index(snapshot)]:
        root.remove(node)
    header = ElementTree.fromstring('''<g font-family="Arial, sans-serif">
      <rect x="1" y="1" width="734" height="1006" rx="15" fill="url(#rim)"/>
      <rect x="6" y="6" width="724" height="996" rx="10" fill="#181817" stroke="#aaa69a"/>
      <rect x="24" y="22" width="45" height="45" rx="5" fill="#ffdc27"/>
      <path transform="translate(29 26)" fill="#171716"
            d="m4 22 2-2 7 2 6-6L8 9l3-3 14 6 6-6c1.7-1.7 3.5-2 4.6-.9 1.1 1.1.7 2.9-.9 4.6l-6 6 6 14-3 3-7-11-6 6 2 7-2 2-5-9z"/>
      <text x="82" y="59" fill="#ffdc27" font-size="43" font-weight="bold">Departures</text>
      <text x="708" y="55" text-anchor="end" fill="#f8f5e9" font-size="26">Zürich · ZRH</text>
    </g>''')
    root.insert(list(root).index(snapshot), header)
    stamp = root.find("{*}text")
    stamp.attrib.update(x="26", y="92", **{"text-anchor": "start", "font-size": "19"})
    labels = ElementTree.SubElement(defs, "g", id="mobile-labels", fill="#ffdc27",
                                    attrib={"font-family": "Arial, sans-serif", "font-size": "20"})
    for name, x, line in MOBILE_FIELDS:
        ElementTree.SubElement(labels, "text", x=str(x), y=str(line - 8)).text = name
    for index, row in enumerate(root.findall("{*}g[@data-row]")):
        y = 147 + 177 * index
        row_index = list(root).index(row)
        lamps = root[row_index + 1]
        lamps.set("transform", f"translate(26 {y + 23.4})")
        root.insert(row_index, ElementTree.Element("path", d=f"M24 {y-39}h688", stroke="#55544f"))
        root.insert(row_index + 1, ElementTree.Element("use", href="#mobile-labels",
                                                      transform=f"translate(0 {y})"))
        row.set("transform", f"translate(0 {y})")
        cells = iter(row)
        for (_, width), (_, x, line) in zip(COLUMNS, MOBILE_FIELDS):
            for letter in range(width):
                next(cells).set("transform", f"translate({x + 22*letter} {line}) scale(1 .78)")
    mobile = BOARD.with_name("splitflap-board-mobile.svg")
    artwork = ElementTree.tostring(root, encoding="utf-8") + b"\n"
    if not mobile.exists() or mobile.read_bytes() != artwork:
        mobile.write_bytes(artwork)


def build(rows, now):
    build_desktop(rows, now)
    build_mobile()


if __name__ == "__main__":
    with urlopen(FEED, timeout=30) as response:
        flights = json.load(response)
    checked = datetime.now(timezone.utc)
    build(next_departures(flights, checked), checked)
