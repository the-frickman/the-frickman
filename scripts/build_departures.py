"""Rebuild the standalone Zürich split-flap SVG with Python's standard library."""

from pathlib import Path
from string import ascii_uppercase, digits
from xml.sax.saxutils import escape

BOARD = Path(__file__).resolve().parents[1] / "assets" / "splitflap-board.svg"
MARKER = "  <!-- BEGIN GENERATED DEPARTURES -->"
# Number, destination and local departure time come from SWISS's ZRH route timetables.
# Gate, desk range and delay are sample operations data. All services here are nonstop.
# time, destination, flight, gate, check-in area, counter range, delay (minutes)
FLIGHTS = [
    ("07:00", "FRANKFURT", "LX3608", "A62", "1", "121-126", 0),
    ("07:05", "LONDON LHR", "LX316", "D43", "1", "121-126", 0),
    ("07:10", "ROME FCO", "LX1726", "A63", "1", "121-126", 0),
    ("07:15", "AMSTERDAM", "LX724", "A74", "3", "301-306", 0),
    ("07:20", "MUNICH", "LX3624", "A67", "1", "121-126", 10),
    ("07:25", "PARIS CDG", "LX632", "A82", "3", "301-306", 0),
    ("12:20", "COPENHAGEN", "LX1270", "A72", "1", "121-126", 0),
    ("12:35", "LISBON", "LX2084", "A73", "3", "301-306", 0),
    ("12:40", "VIENNA", "LX3534", "B33", "1", "121-126", 0),
    ("12:45", "BERLIN", "LX966", "A71", "3", "301-306", 15),
    ("13:05", "TOKYO NARITA", "LX160", "E46", "1", "111-116", 0),
    ("13:10", "NEW YORK JFK", "LX14", "E53", "1", "111-116", 0),
    ("20:45", "AMSTERDAM", "LX736", "A64", "1", "121-126", 0),
    ("20:50", "VIENNA", "LX3558", "B39", "3", "301-306", 0),
    ("20:55", "PARIS CDG", "LX646", "A72", "1", "121-126", 0),
    ("21:05", "BERLIN", "LX962", "A83", "3", "301-306", 15),
    ("22:30", "HONG KONG", "LX138", "E42", "1", "111-116", 0),
    ("22:35", "SINGAPORE", "LX176", "E56", "1", "111-116", 0),
]
COLUMNS = ((51, 7), (222, 13), (518, 3), (597, 5), (719, 5),
           (848, 1), (910, 1), (1008, 7), (1177, 3), (1260, 10))
ROW_COUNT = 6
INTERVAL = 18  # seconds of illustration per departure
CYCLE = INTERVAL * len(FLIGHTS)
STEP = .12
ATTENTION = {"FINAL CALL", "BOARDING", "GATE OPEN"}


def minutes(hhmm):
    hour, minute = map(int, hhmm.split(":"))
    return 60 * hour + minute


def fields(index, row, departed):
    time, city, flight, gate, area, desks, delay = FLIGHTS[(index + row) % len(FLIGHTS)]
    ahead = (minutes(time) - minutes(FLIGHTS[index][0])) % 1440
    estimate = ""
    if delay:
        hour, minute = divmod((minutes(time) + delay) % 1440, 60)
        estimate = f"{hour:02}:{minute:02}"
    if row == 0:
        remark = "DEPARTED" if departed else "FINAL CALL"
    elif delay:
        remark = "DELAYED"
    elif row == 1 and ahead <= 35:
        remark = "BOARDING"
    elif row < 4 and ahead <= 50:
        remark = "GATE OPEN"
    else:
        remark = "ON TIME"
    return (f"{flight[:2]} {flight[2:]:>4}", city, "", time, estimate,
            gate[0], area, desks, gate, remark)


def row_history(row):
    history = [(0, fields(0, row, False))]
    for index in range(len(FLIGHTS)):
        base = index * INTERVAL
        if row == 0:
            history.append((base + 4.8, fields(index, row, True)))
        history.append((base + 10.8, fields((index + 1) % len(FLIGHTS), row, False)))
    return history


def ref(char):
    return "#g" + {" ": "_", ":": "c"}.get(char, char)


def discrete(attribute, events):
    """SMIL samples stay constant between keys, including at the loop boundary."""
    times = ";".join(f"{time / CYCLE:.6f}".rstrip("0").rstrip(".") for time, _ in events)
    values = ";".join(str(value) for _, value in events)
    return (f'<animate attributeName="{attribute}" calcMode="discrete" dur="{CYCLE}s" '
            f'keyTimes="{times}" values="{values}" repeatCount="indefinite"/>')


def print_track(name, events):
    return f'<use id="{name}" href="{events[0][1]}">{discrete("href", events)}</use>'


def motor(tile_id, x, row, track, bounds):
    """A released card exposes the next top and turns into the next bottom."""
    first = track[0][1]
    chars = {char for _, char in track}
    if len(chars) == 1:
        return f'<use href="{ref(first)}"/>' if first != " " else ""
    alphabet = " " + ascii_uppercase + digits + ":-"
    if chars <= set(digits + " :"):
        alphabet = (" " if " " in chars else "") + digits + (":" if ":" in chars else "")
    elif chars <= set(ascii_uppercase + " "):
        alphabet = " " + ascii_uppercase
    # All starts lie on this wheel's repeating 120 ms motor beat.
    phase = ((x + 3 * row) % 7) * .012
    stagger = (row + (x % 3)) * STEP + phase
    top = [(0, ref(first))]
    bottom = [(0, ref(first))]
    moving = [(0, 0)]
    old = first
    for change, goal in track[1:]:
        count = (alphabet.index(goal) - alphabet.index(old)) % len(alphabet)
        if not count:
            continue
        start = change + stagger
        stop = start + STEP * count
        earliest, latest = bounds.get(change, (start, stop))
        bounds[change] = min(start, earliest), max(stop, latest)
        moving.extend(((start, 1), (stop, 0)))
        for step in range(count):
            old = alphabet[(alphabet.index(old) + 1) % len(alphabet)]
            top.append((start + step * STEP, ref(old)))
            bottom.append((start + (step + 1) * STEP, ref(old)))
    for events in (top, bottom, moving):
        events.append((CYCLE, events[0][1]))
    a, b = tile_id + "t", tile_id + "b"
    return f'''<g class="rest-face"><use href="{ref(first)}"/></g>
<g class="animated-face">
  <defs>{print_track(a, top)}{print_track(b, bottom)}</defs>
  <g clip-path="url(#top-clip)"><use href="#{a}"/></g>
  <g clip-path="url(#bottom-clip)"><use href="#{b}"/></g>
  <g opacity="0">{discrete("opacity", moving)}
    <g transform="translate(0 30)"><g>
      <animateTransform attributeName="transform" type="scale" dur=".12s" begin="{phase:.3f}s" repeatCount="indefinite"
        keyTimes="0;.20;.38;.55;.68;.8;1" values="1 1;1 .98;1 .77;1 0;1 -.65;1 -1;1 -1"/>
      <g transform="translate(0 -30)">
        <g clip-path="url(#top-clip)">
          <animate attributeName="opacity" calcMode="discrete" begin="{phase:.3f}s" dur=".12s" repeatCount="indefinite" keyTimes="0;.55;1" values="1;0;0"/>
          <use href="#upper"/><use href="#{b}"/>
        </g>
        <g transform="translate(0 60) scale(1 -1)" clip-path="url(#bottom-clip)" opacity="0">
          <animate attributeName="opacity" calcMode="discrete" begin="{phase:.3f}s" dur=".12s" repeatCount="indefinite" keyTimes="0;.55;1" values="0;1;1"/>
          <use href="#lower"/><use href="#{a}"/>
        </g>
      </g>
    </g></g>
  </g>
</g>'''


def lamps(row, history, bounds):
    first = int(history[0][1][-1] in ATTENTION)
    schedule = [(0, first)]
    for change, data in history[1:]:
        if change in bounds:
            start, stop = bounds[change]
            schedule.extend(((start, 0), (stop, int(data[-1] in ATTENTION))))
    schedule.append((CYCLE, first))
    steady = '<use class="rest-face" href="#attention-pair"/>' if first else ""
    return (f'<g transform="translate(27 {163.4 + 43*row:.1f})"><use href="#dark-pair"/>{steady}'
            f'<g class="motion-lamps" opacity="{first}"><use href="#attention-pair"/>'
            f'{discrete("opacity", schedule)}</g></g>')


def build():
    shell, marker, _ = BOARD.read_text().partition(MARKER)
    if not marker:
        raise ValueError("SVG artwork is missing its departures marker")
    parts = [shell.rstrip(), MARKER]
    for row in range(ROW_COUNT):
        history = row_history(row)
        bounds = {}
        label = escape(" · ".join(filter(None, history[0][1])))
        parts.append(f'<g data-row="{row}" aria-label="{label}" fill="#f8f5e9" '
                     f'transform="translate(0 {143 + 43*row}) scale(1 .68)">')
        for field, (x, width) in enumerate(COLUMNS):
            values = [(time, data[field].ljust(width)) for time, data in history]
            if any(len(value) != width for _, value in values):
                raise ValueError(f"Field {field} exceeds its {width} flap slots")
            for i in range(width):
                pos = x + 22*i
                track = [(time, value[i]) for time, value in values]
                face = motor(f"r{row}x{pos}", pos, row, track, bounds)
                parts.append(f'<g transform="translate({pos} 0)"><use href="#tile"/>'
                             f'{face}<use href="#seam"/></g>')
        parts.extend(("</g>", lamps(row, history, bounds)))
    parts.append("</svg>\n")
    BOARD.write_text("\n".join(parts))


if __name__ == "__main__":
    build()
