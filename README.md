# Das Keyboard X50Q USB lighting protocol

This note documents the lighting protocol reverse-engineered for the Das
Keyboard X50Q (`VID:PID 24f0:202b`). The accompanying `x50q_walk.py` is a
standalone reference sender; it constructs reports directly and does not need
capture files at runtime.

The packet format, key slots, and effect values below come from controlled
Q Software USB captures. The user verified direct RGB writes and the key/slot
walk on the physical keyboard. Effect mode and effect-color writes were decoded
from captures and should be hardware-checked before relying on every mode.

## USB interface

- Vendor/product ID: `24f0:202b`
- HID interface: `2`
- Interrupt OUT endpoint: `0x03`
- Report size: `64` bytes
- Inter-report delay used by the reference sender: `2 ms`

The reference sender uses PyUSB/libusb, claims interface 2, and writes reports
to endpoint `0x03`. It enumerates devices by VID:PID rather than assuming a
USB bus number. One match is selected automatically. If multiple X50Qs are
connected, it prints their USB bus/address pairs and requires an explicit
`--device BUS:ADDRESS` selection. For example, `--device 5:2` selects bus 5,
device address 2; use `lsusb` to find current values.

## Report framing

Each report starts with a four-byte header:

| Byte | Meaning |
|---|---|
| 0 | `0x07`, report/protocol ID |
| 1 | Command opcode |
| 2 | `0x06`, command marker |
| 3 | Chunk index |

The remaining 60 bytes are the chunk payload. A complete observed state update
contains 25 reports in this order:

1. Opcode `0x0F`, chunks 0–2
2. Opcode `0x0E`, chunks 0–2
3. Opcode `0x0A`, chunks 0–7
4. Opcode `0x0D`, chunks 0–2
5. Opcode `0x09`, chunks 0–7

The `0x0F`, `0x0E`, and `0x0D` payloads are zero-filled except for the effect
selector fields described below. Each `0x0A` and `0x09` array has 480 bytes:
eight 60-byte chunks. The first 432 bytes carry three 144-byte channel planes;
the final 48 bytes are padding.

## RGB slot arrays

Each channel has 144 slots. For slot s and channel c (`R=0`, `G=1`, `B=2`),
the byte position in the flattened array is:

```text
position = s + 144 * c
chunk = position // 60
payload_offset = position % 60
report_byte_offset = 4 + payload_offset
```

The captured `0x0A` and `0x09` arrays share the same planar layout. Changing a
key's normal color updates its slot in the `0x09` plane. Changing the
keydown-effect color updates that slot in the `0x0A` plane. If no separate
effect color is supplied, the reference script mirrors the normal color into
both planes.

The Q button ring was observed at slots `117`, `118`, `126`, and `131`. Ring
color changes appeared in the `0x09` plane. The two undercarriage controls map
to two slots each: left pipe `36` and `42`; right pipe `51` and `123`.

The physical key mapping is embedded in `KEYS` in `x50q_walk.py`. It was
derived by changing one key at a time. Cross-capture checks include X=`33`,
A=`39`, L=`84`, and Numpad Enter=`121`.

## Keydown effect selector

The selector pair is stored at report byte offset `37` (zero-based), equivalent
to payload offset `33`, in chunk 0 of opcodes `0x0F` and `0x0E`. The captured
values are:

| Effect | `0x0F` byte 37 | `0x0E` byte 37 |
|---|---:|---:|
| Set color | `0x02` | `0x00` |
| Blink | `0x03` | `0x04` |
| Breathe | `0x03` | `0x01` |
| Ripple | `0x03` | `0x05` |
| Laser | `0x03` | `0x07` |
| Color cycle | `0x05` | `0x03` |
| Inward ripple | `0x05` | `0x06` |
| None | `0x05` | `0x00` |

The capture shows the selector values but does not fully establish whether all
effects trigger only on the selected key or have broader keydown behavior.

## Reference sender

Examples:

```bash
python3 x50q_walk.py --key x --color 000000 --effect ripple --effect-color ff0000
python3 x50q_walk.py --key leftpipe --color ff0000
python3 x50q_walk.py --key q-ring --color 0000ff
python3 x50q_walk.py --device 5:2 --key x --color ff0000
python3 x50q_walk.py --list-keys
```

Each call sends a complete 25-report state. Unspecified RGB slots are written
as black, so this script is useful for protocol validation and visual mapping.
