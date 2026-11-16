#!/usr/bin/env python3
"""Control X50Q LEDs using its native 25-report USB protocol.

The report builder is standalone: it does not parse capture files. Protocol
layout and observed command values are documented in X50Q_PROTOCOL.md.

Protocol summary:
    Device: VID:PID 24f0:202b, interface 2, interrupt OUT endpoint 0x03.
    Each update: 25 reports of 64 bytes, sent in the order implemented by
    make_batch(). Each report starts with 07 opcode 06 chunk, then 60 payload
    bytes. Color arrays contain 144-slot R, G, and B planes with 60-byte
    chunks and 48 bytes of trailing padding.

The key-to-slot map is based on controlled one-key-at-a-time color captures.
The effect selector values are based on Q Software captures. Hardware behavior
for each effect/color combination should be confirmed on the target device.

Example:
    sudo python3 x50q_walk.py --rgb ff0000 --delay 0.8
    sudo python3 x50q_walk.py --key x --color 00ff00
    sudo python3 x50q_walk.py --key x --color 000000 --effect ripple --effect-color ff0000
    sudo python3 x50q_walk.py --key leftpipe --color ff0000
    sudo python3 x50q_walk.py --key q-ring --color 0000ff
    sudo python3 x50q_walk.py --device 5:2 --key x --color ff0000

By default each step lights only the current target (spotlight mode). Pass
--accumulate to leave previously visited LEDs lit. Use --loops 0 to repeat
until Ctrl-C. A single matching keyboard is selected automatically; with
multiple matches, use --device BUS:ADDRESS to choose one.
"""

import argparse
import re
import sys
import time


VENDOR_ID = 0x24F0
PRODUCT_ID = 0x202B
INTERFACE = 2
OUT_ENDPOINT = 0x03
REPORT_SIZE = 64
PAYLOAD_SIZE = 60
SLOTS = 144
PLANE_STRIDE = 144
ARRAY_BYTES = 480  # Eight 60-byte chunks; final 48 bytes are padding.


# Order follows the user's controlled walk. Values are the RGB array slot IDs
# inferred from one-change-at-a-time captures. Pipe controls update two slots.
KEYS = [
    ("Esc", (45,)),
    ("F1", (27,)), ("F2", (18,)), ("F3", (9,)), ("F4", (14,)),
    ("F5", (0,)), ("F6", (5,)), ("F7", (90,)), ("F8", (95,)),
    ("F9", (77,)), ("F10", (63,)), ("F11", (68,)), ("F12", (54,)),
    ("Print Screen", (59,)), ("Scroll Lock", (99,)), ("Pause", (104,)),
    ("Brightness", (111,)), ("Play", (120,)), ("Fast Forward", (129,)),
    ("`", (46,)),
    ("1", (37,)), ("2", (28,)), ("3", (19,)), ("4", (10,)),
    ("5", (15,)), ("6", (1,)), ("7", (6,)), ("8", (91,)),
    ("9", (96,)), ("0", (81,)), ("-", (72,)), ("=", (64,)),
    ("Backspace", (60,)), ("Insert", (61,)), ("Home", (105,)),
    ("Page Up", (106,)), ("Num Lock", (102,)), ("Num /", (110,)),
    ("Num *", (128,)), ("Num -", (119,)),
    ("Tab", (47,)), ("Q", (38,)), ("W", (29,)), ("E", (20,)),
    ("R", (11,)), ("T", (16,)), ("Y", (2,)), ("U", (92,)),
    ("I", (82,)), ("O", (87,)), ("P", (73,)), ("[", (65,)),
    ("]", (69,)), ("\\", (56,)), ("Delete", (101,)),
    ("End", (103,)), ("Page Down", (100,)), ("Num 7", (142,)),
    ("Num 8", (115,)), ("Num 9", (133,)), ("Num +", (124,)),
    ("Caps Lock", (48,)), ("A", (39,)), ("S", (30,)), ("D", (21,)),
    ("F", (25,)), ("G", (12,)), ("H", (3,)), ("J", (93,)),
    ("K", (83,)), ("L", (84,)), (";", (74,)), ("'", (66,)),
    ("Enter", (58,)), ("Num 4", (139,)), ("Num 5", (112,)),
    ("Num 6", (130,)),
    ("Left Shift", (49,)), ("Z", (31,)), ("X", (33,)),
    ("C", (24,)), ("V", (22,)), ("B", (13,)), ("N", (4,)),
    ("M", (94,)), ("<", (85,)), (">", (86,)), ("?", (76,)),
    ("Right Shift", (70,)), ("Up", (135,)), ("Num 1", (136,)),
    ("Num 2", (109,)), ("Num 3", (127,)), ("Num Enter", (121,)),
    ("Left Ctrl", (50,)), ("Windows", (41,)), ("Left Alt", (32,)),
    ("Space", (23,)), ("Right Alt", (88,)), ("Fn", (79,)),
    ("Context Menu", (78,)), ("Right Ctrl", (67,)),
    ("Left", (140,)), ("Down", (137,)), ("Right", (138,)),
    ("Num 0", (141,)), ("Num .", (132,)),
    ("leftpipe", (36, 42)),
    ("rightpipe", (51, 123)),
]

Q_RING_SLOTS = (117, 118, 126, 131)
TARGETS = KEYS + [("Q button ring", Q_RING_SLOTS)]

# Captured from Q Software in the order: Set color, Blink, Breathe, Ripple,
# Laser, Color cycle, Inward ripple, None. The pair is stored at byte 37 of
# chunk zero in opcodes 0x0F and 0x0E respectively.
EFFECT_CODES = {
    "set-color": (0x02, 0x00),
    "blink": (0x03, 0x04),
    "breathe": (0x03, 0x01),
    "ripple": (0x03, 0x05),
    "laser": (0x03, 0x07),
    "color-cycle": (0x05, 0x03),
    "inward-ripple": (0x05, 0x06),
    "none": (0x05, 0x00),
}

# CLI names are intentionally short for the controls most useful while
# checking the map. Printable punctuation keys can be entered by their name.
LABEL_IDS = {
    "Print Screen": "prtsc", "Scroll Lock": "scrlk",
    "Brightness": "bright", "Fast Forward": "ff", "`": "tilde",
    "Backspace": "bksp", "Page Up": "pgup", "Num Lock": "numlk",
    "Num /": "num/", "Num *": "num*", "Num -": "num-",
    "Delete": "del", "Page Down": "pgdn", "Num +": "num+",
    "Caps Lock": "caps", "Left Shift": "lshift", "Right Shift": "rshift",
    "Num Enter": "numenter", "Left Ctrl": "lctrl", "Windows": "win",
    "Left Alt": "lalt", "Right Alt": "ralt", "Context Menu": "context",
    "Right Ctrl": "rctrl", "Num .": "num.",
    "Num 7": "num7", "Num 8": "num8", "Num 9": "num9",
    "Num 4": "num4", "Num 5": "num5", "Num 6": "num6",
    "Num 1": "num1", "Num 2": "num2", "Num 3": "num3",
    "Num 0": "num0",
    "[": "[", "]": "]", "\\": "\\", ";": ";", "'": "'",
    "<": "<", ">": ">", "?": "?", "-": "-", "=": "=",
}
KEY_MAP = {
    LABEL_IDS.get(label, label.lower()): (label, slots)
    for label, slots in KEYS
}
KEY_MAP["q-ring"] = ("Q button ring", Q_RING_SLOTS)
KEY_ALIASES = {
    "esc": "esc", "print-screen": "prtsc", "scroll-lock": "scrlk",
    "brightness": "bright", "fast-forward": "ff", "grave": "tilde",
    "backspace": "bksp", "insert": "ins", "page-up": "pgup",
    "num-lock": "numlk", "num-divide": "num/", "num-multiply": "num*",
    "num-minus": "num-", "delete": "del", "page-down": "pgdn",
    "num-plus": "num+", "caps-lock": "caps", "left-shift": "lshift",
    "right-shift": "rshift", "num-enter": "numenter", "left-ctrl": "lctrl",
    "windows": "win", "left-alt": "lalt", "right-alt": "ralt",
    "context-menu": "context", "right-ctrl": "rctrl", "num-decimal": "num.",
    "q-button-ring": "q-ring",
    "left-pipe": "leftpipe", "right-pipe": "rightpipe", "qring": "q-ring",
    "minus": "-", "equals": "=", "left-bracket": "[",
    "right-bracket": "]", "backslash": "\\", "semicolon": ";",
    "apostrophe": "'", "less-than": "<", "greater-than": ">",
    "question-mark": "?",
}


def resolve_key(value):
    name = value.strip().lower()
    name = KEY_ALIASES.get(name, name)
    if name not in KEY_MAP:
        raise ValueError(f"unknown key {value!r}; use --list-keys to see names")
    return KEY_MAP[name]


def make_color_array(colors):
    """Pack slot-to-(R, G, B) values into the observed planar array."""
    data = bytearray(ARRAY_BYTES)
    for slot, rgb in colors.items():
        if not 0 <= slot < SLOTS:
            raise ValueError(f"LED slot outside 0..{SLOTS - 1}: {slot}")
        for channel, value in enumerate(rgb):
            data[slot + channel * PLANE_STRIDE] = value
    return data


def make_report(opcode, chunk, payload):
    """Create one 64-byte output report with its 4-byte protocol header."""
    if len(payload) != PAYLOAD_SIZE:
        raise ValueError(f"Report payload must be {PAYLOAD_SIZE} bytes")
    report = bytes((0x07, opcode, 0x06, chunk)) + payload
    if len(report) != REPORT_SIZE:
        raise ValueError(f"Report must be {REPORT_SIZE} bytes")
    return report


def make_batch(slot_colors, ring_color, effect="set-color", effect_colors=None):
    """Build a complete state update from protocol fields.

    Opcodes 0x0F, 0x0E and 0x0D are fixed zero-filled three-chunk blocks.
    0x0A carries the keydown-effect color plane; 0x09 carries the steady
    color plane and Q ring. If no separate effect color is supplied, the
    selected key colors are mirrored into both. The Q ring was observed
    changing only in 0x09, so its four slots are added to that stream alone.
    """
    # Opcode 0x0A carries the keydown-effect color plane. If a separate color
    # wasn't supplied, mirror the steady color for backward compatibility.
    effect_array = make_color_array(
        slot_colors if effect_colors is None else effect_colors
    )
    ring_stream_colors = dict(slot_colors)
    if ring_color is not None:
        for slot in Q_RING_SLOTS:
            ring_stream_colors[slot] = ring_color
    ring_stream = make_color_array(ring_stream_colors)

    reports = []
    effect_group, effect_mode = EFFECT_CODES[effect]
    for opcode, value in ((0x0F, effect_group), (0x0E, effect_mode)):
        for chunk in range(3):
            payload = bytearray(PAYLOAD_SIZE)
            if chunk == 0:
                payload[33] = value  # report byte 37
            reports.append(make_report(opcode, chunk, payload))
    for opcode, data in ((0x0A, effect_array), (0x0D, None), (0x09, ring_stream)):
        chunks = range(3) if opcode == 0x0D else range(8)
        for chunk in chunks:
            payload = (
                bytes(PAYLOAD_SIZE)
                if data is None
                else data[chunk * PAYLOAD_SIZE:(chunk + 1) * PAYLOAD_SIZE]
            )
            reports.append(make_report(opcode, chunk, payload))
    if len(reports) != 25:
        raise AssertionError(f"Expected 25 reports, built {len(reports)}")
    return reports


def send_batch(device, slot_colors, ring_color, effect="set-color", effect_colors=None):
    for report_number, report in enumerate(
        make_batch(slot_colors, ring_color, effect, effect_colors), 1
    ):
        try:
            written = device.write(OUT_ENDPOINT, report, timeout=1000)
        except Exception as exc:
            raise RuntimeError(
                f"USB write {report_number}/25 failed: opcode=0x{report[1]:02X}, "
                f"chunk={report[3]}, endpoint=0x{OUT_ENDPOINT:02X}: {exc}"
            ) from exc
        if written != REPORT_SIZE:
            raise OSError(
                f"Short USB write {report_number}/25: {written}/{REPORT_SIZE} bytes"
            )
        time.sleep(0.002)


def open_keyboard(device_selector=None):
    try:
        import usb.core
        import usb.util
    except ImportError as exc:
        raise RuntimeError(
            "PyUSB is required (install your distro's python3-usb package)"
        ) from exc

    devices = list(usb.core.find(
        find_all=True, idVendor=VENDOR_ID, idProduct=PRODUCT_ID
    ))
    if not devices:
        raise RuntimeError(
            f"X50Q {VENDOR_ID:04x}:{PRODUCT_ID:04x} not found. "
            "Verify the USB connection and host permissions."
        )

    if device_selector is not None:
        bus, address = device_selector
        device = next(
            (
                candidate for candidate in devices
                if candidate.bus == bus and candidate.address == address
            ),
            None,
        )
        if device is None:
            found = ", ".join(
                f"{candidate.bus}:{candidate.address}" for candidate in devices
            )
            raise RuntimeError(
                f"No X50Q found at USB {bus}:{address}. "
                f"Matching devices: {found}"
            )
    elif len(devices) == 1:
        device = devices[0]
    else:
        found = ", ".join(
            f"{candidate.bus}:{candidate.address}" for candidate in devices
        )
        raise RuntimeError(
            f"Found {len(devices)} X50Q keyboards. Matching USB "
            f"BUS:ADDRESS pairs: {found}. "
            "Select one with --device BUS:ADDRESS."
        )

    detached = False
    try:
        try:
            if device.is_kernel_driver_active(INTERFACE):
                device.detach_kernel_driver(INTERFACE)
                detached = True
        except NotImplementedError:
            pass
        usb.util.claim_interface(device, INTERFACE)
        return device, usb.util, detached
    except Exception:
        if detached:
            try:
                device.attach_kernel_driver(INTERFACE)
            except Exception:
                pass
        raise


def parse_rgb(value):
    if not re.fullmatch(r"[0-9a-fA-F]{6}", value):
        raise argparse.ArgumentTypeError("use six hex digits, for example ff0000")
    return tuple(bytes.fromhex(value))


def parse_device_selector(value):
    match = re.fullmatch(r"(\d+):(\d+)", value)
    if not match:
        raise argparse.ArgumentTypeError(
            "use BUS:ADDRESS, for example 5:2 (see lsusb)"
        )
    return tuple(map(int, match.groups()))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rgb", "--color", dest="rgb", type=parse_rgb,
                        default=parse_rgb("ff0000"),
                        help="test color as RRGGBB (default: ff0000)")
    parser.add_argument("--effect-color", type=parse_rgb,
                        help="keydown animation color as RRGGBB (defaults to --color)")
    parser.add_argument("--delay", type=float, default=0.8,
                        help="seconds to display each target (default: 0.8)")
    parser.add_argument("--loops", type=int, default=1,
                        help="number of full passes; 0 repeats until Ctrl-C")
    parser.add_argument("--accumulate", action="store_true",
                        help="leave earlier targets lit instead of spotlighting one")
    parser.add_argument("--key", metavar="NAME",
                        help="set one target instead of walking (e.g. x, leftpipe, q-ring)")
    parser.add_argument("--device", type=parse_device_selector, metavar="BUS:ADDRESS",
                        help="select a specific matching keyboard (e.g. 5:2)")
    parser.add_argument("--effect", choices=tuple(EFFECT_CODES), default="set-color",
                        help="keydown effect (default: set-color)")
    parser.add_argument("--list-keys", action="store_true",
                        help="list accepted --key names and exit")
    args = parser.parse_args()
    if args.delay < 0:
        parser.error("--delay cannot be negative")
    if args.loops < 0:
        parser.error("--loops cannot be negative")
    if args.list_keys:
        print(" ".join(sorted(KEY_MAP)))
        return 0
    resolved = None
    if args.key is not None:
        try:
            resolved = resolve_key(args.key)
        except ValueError as exc:
            parser.error(str(exc))

    device, usb_util, detached = open_keyboard(args.device)
    accumulated = {}
    accumulated_ring = None
    try:
        if resolved is not None:
            label, slots = resolved
            is_ring = label == "Q button ring"
            active = {} if is_ring else {slot: args.rgb for slot in slots}
            ring_color = args.rgb if is_ring else None
            effect_rgb = args.effect_color or args.rgb
            effect_colors = {slot: effect_rgb for slot in active}
            color_description = f"base #{bytes(args.rgb).hex().upper()}"
            if not is_ring:
                color_description += f", effect #{bytes(effect_rgb).hex().upper()}"
            print(
                f"Setting {label} (slot{'s' if len(slots) != 1 else ''} "
                f"{', '.join(map(str, slots))}) -> {color_description} [{args.effect}]",
                flush=True,
            )
            send_batch(device, active, ring_color, args.effect, effect_colors)
            return 0

        pass_number = 0
        while args.loops == 0 or pass_number < args.loops:
            pass_number += 1
            for index, (label, slots) in enumerate(TARGETS, start=1):
                is_ring = label == "Q button ring"
                if args.accumulate and not is_ring:
                    for slot in slots:
                        accumulated[slot] = args.rgb
                    active = dict(accumulated)
                    ring_color = accumulated_ring
                elif args.accumulate:
                    active = dict(accumulated)
                    accumulated_ring = args.rgb
                    ring_color = accumulated_ring
                elif is_ring:
                    active = {}
                    ring_color = args.rgb
                else:
                    active = {slot: args.rgb for slot in slots}
                    ring_color = None
                effect_rgb = args.effect_color or args.rgb
                effect_colors = {slot: effect_rgb for slot in active}
                print(
                    f"Pass {pass_number}: [{index}/{len(TARGETS)}] "
                    f"{label} -> base #{bytes(args.rgb).hex().upper()}, "
                    f"effect #{bytes(effect_rgb).hex().upper()} [{args.effect}]",
                    flush=True,
                )
                send_batch(device, active, ring_color, args.effect, effect_colors)
                time.sleep(args.delay)
    except KeyboardInterrupt:
        print("\nStopped; the last displayed target remains lit.")
    finally:
        try:
            usb_util.release_interface(device, INTERFACE)
        finally:
            if detached:
                try:
                    device.attach_kernel_driver(INTERFACE)
                except Exception:
                    pass
            usb_util.dispose_resources(device)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)
