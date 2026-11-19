# Das Keyboard X50Q USB lighting protocol

This document describes how to address the Das Keyboard X50Q (`VID:PID
24f0:202b`), construct lighting payloads, and send a complete device state.
This was obtained by USB captures of the keyboard while sending commands to
the keyboard using the Q Software.

The final section of this document explains the `x50q_walk.py` reference 
sender. This script acts as an example on how to construct the command payload
to send to the keyboard's lighting controller.

## USB transport

| Property | Value |
|---|---|
| Vendor ID | `0x24f0` |
| Product ID | `0x202b` |
| HID interface | `2` |
| Interrupt OUT endpoint | `0x03` |
| Report length | `64` bytes |
| Payload length | `60` bytes |

Claim interface 2 and send each report to endpoint `0x03`. The reference
sender waits 2 ms between reports. Device selection should use VID:PID; bus
and device addresses can change after reconnecting.

## Report format

Every report has a four-byte header followed by a 60-byte payload:

| Report byte | Meaning |
|---:|---|
| 0 | `0x07`, report ID |
| 1 | Command opcode |
| 2 | `0x06`, command marker |
| 3 | Chunk index, starting at zero |
| 4–63 | Chunk payload |

Large data blocks are split into sequential 60-byte chunks. For any data
offset `p` in a block:

```text
chunk = p // 60
payload_offset = p % 60
report_byte_offset = 4 + payload_offset
```

## Complete state update

A complete lighting update consists of 25 reports sent in this order:

| Order | Opcode | Chunks | Purpose |
|---:|---:|---:|---|
| 1 | `0x0F` | 0–2 | First keydown-effect selector |
| 2 | `0x0E` | 0–2 | Second keydown-effect selector |
| 3 | `0x0A` | 0–7 | Keydown-effect RGB values |
| 4 | `0x0D` | 0–2 | Per-slot lighting-effect selectors |
| 5 | `0x09` | 0–7 | Resting RGB values |

The selector blocks `0x0F`, `0x0E`, and `0x0D` use three 60-byte chunks each.
The color blocks `0x0A` and `0x09` use eight chunks each. Pad unused bytes
with zero. Send all 25 reports even when only one LED changes; slots not
specified in either color array are consequently set to black.

## RGB payloads

Opcodes `0x0A` and `0x09` each carry a 480-byte array. The first 432 bytes are
three 144-byte channel planes; the final 48 bytes are padding. For LED slot
`s` and channel `c` (`R=0`, `G=1`, `B=2`), the byte offset in either array is:

```text
position = s + 144 * c
chunk = position // 60
payload_offset = position % 60
report_byte_offset = 4 + payload_offset
```

Use opcode `0x09` for resting/static colors. Use opcode `0x0A` for the color
associated with a keydown effect. When no separate keydown color is needed,
write the same RGB values to both arrays.

The keyboard and auxiliary LEDs use slots in this shared address space. The Q
button ring occupies slots `117`, `118`, `126`, and `131`. The left pipe uses
slots `36` and `42`; the right pipe uses `51` and `123`. The full key-to-slot
map is defined by `KEYS` in `x50q_walk.py`; for example, X=`33`, A=`39`,
L=`84`, and Numpad Enter=`121`.

## Keydown effects

The keydown effect is selected by a pair of selector bytes: one in opcode
`0x0F`, the other in opcode `0x0E`. Both are at report byte 37 (payload offset
33) in chunk 0. The other selector-block payload bytes are zero. The selector
pair is shared state; it is not indexed by LED slot.

| Effect | `0x0F`, byte 37 | `0x0E`, byte 37 |
|---|---:|---:|
| Set color | `0x02` | `0x00` |
| Blink | `0x03` | `0x04` |
| Breathe | `0x03` | `0x01` |
| Ripple | `0x03` | `0x05` |
| Laser | `0x03` | `0x07` |
| Color cycle | `0x05` | `0x03` |
| Inward ripple | `0x05` | `0x06` |
| None | `0x05` | `0x00` |

The keydown-effect color is stored by slot in `0x0A`; its resting color is in
the matching `0x09` slot. For example, a red keydown blink on X with a black
resting color uses selector values `0x03` and `0x04`, writes red to X's `0x0A`
RGB slot, and writes black to X's `0x09` RGB slot. The selector pair alone
does not indicate whether the effect triggers only on the selected key or
more broadly across the keyboard.

## Per-key lighting effects

Opcode `0x0D` contains a 180-byte selector block split across chunks 0–2. The
first 144 bytes map directly to LED slots; the remaining 36 bytes are padding.
For slot `s`, place the selector at block offset `s` using the same chunk and
payload-offset calculation as above. For example, X is slot 33, so its
selector is at report byte 37 of chunk 0.

| Per-key mode | Selector |
|---|---:|
| Direct/static color | `0x00` |
| Breathe | `0x01` |
| Color cycle | `0x03` |
| Blink | `0x04` |

`Set color` and `None` both use selector `0x00`. To represent None, set the
slot's color to black in both `0x09` and `0x0A`. For the other modes, place the
desired LED colors in the two RGB arrays; each slot can have a different color.

## Constructing the payloads

To build a complete update:

1. Initialize two 480-byte RGB arrays (`0x0A` and `0x09`) and a 180-byte
   per-key selector array (`0x0D`) to zero.
2. For each LED, write its resting RGB value to its slot in `0x09` and its
   keydown-effect RGB value to the matching slot in `0x0A`.
3. Write the per-key mode byte for each LED slot in `0x0D`; leave Direct or
   unspecified slots at zero.
4. Set the keydown-effect selector bytes at payload offset 33 in chunk 0 of
   `0x0F` and `0x0E`. Leave the other bytes in these selector blocks at zero.
5. Split each array into 60-byte payload chunks, prepend the four-byte report
   header, and send all chunks in the order listed above.

## Reference sender: `x50q_walk.py`

The Python sender builds the protocol reports directly. Use `--key NAME` to
set a single key or auxiliary LED target. Without `--key`, it walks through
the targets in the order defined by `TARGETS` in the script. At each step it
sends a complete 25-report state with the selected target set to `--rgb` and
all other unspecified slots black. It prints the target name before sending,
waits for `--delay` seconds (default `0.8`), then advances to the next target.
This makes the lit key move across the keyboard one target at a time.

With `--accumulate`, the sender leaves each visited target at `--rgb` as it
advances, so the number of lit targets grows through the walk. `--loops 0`
repeats the full walk until interrupted. `--list-keys` prints valid names. Use
`--device BUS:ADDRESS` to choose a particular keyboard or when more than one
X50Q is connected. Get its current bus and device address from
`lsusb -d 24f0:202b`; for example, bus 5 and device 2 are written `5:2`.
The address can change after reconnecting the keyboard.

```bash
# Light each target red for 0.8 seconds, one at a time; the previous target turns off.
python3 x50q_walk.py --rgb ff0000 --delay 0.8
# Walk all targets in red and leave each visited target lit.
python3 x50q_walk.py --rgb ff0000 --accumulate
# Repeat the target walk until Ctrl-C.
python3 x50q_walk.py --rgb ff0000 --loops 0

# Set only X to red in Direct/static mode.
python3 x50q_walk.py --key x --color ff0000
# Set X to breathe in blue.
python3 x50q_walk.py --key x --key-effect breathe --key-effect-color 0000ff
# Set X to blink red when pressed, with a green resting color.
python3 x50q_walk.py --key x --color 00ff00 --keydown-effect blink --keydown-effect-color ff0000

# Walk the targets on bus 5, device 2.
python3 x50q_walk.py --device 5:2 --rgb ff0000 --delay 0.8
# Set X red on bus 5, device 2.
python3 x50q_walk.py --device 5:2 --key x --color ff0000

# List valid --key names.
python3 x50q_walk.py --list-keys
```
