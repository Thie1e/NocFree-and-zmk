<!-- SPDX-License-Identifier: MIT -->

# ISO layout

This branch targets the **ISO** NocFree &, not the ANSI one. ISO carries one
key more than ANSI and shuffles three keycaps on the right half.

## National layouts are the host's job, not the firmware's

HID keycodes are positional. The key at the ANSI-`Y` position sends usage
`0x1C` whatever is printed on it; a host set to German prints `z`. So there is
no "German firmware" to build, and this keymap is *not* a German map — it is
the standard positional map plus the two codes ANSI has no room for:

| Binding | Position | German host prints |
|---|---|---|
| `&kp NON_US_BSLH` | between left shift and `Z` | `< > \|` |
| `&kp NON_US_HASH` | left of the ISO Enter | `# '` |

Set the layout in the operating system. Nothing else is needed for German,
French, Spanish or any other ISO national layout.

## What differs from the ANSI port

The left half gains one input; the right half is electrically identical to
ANSI and only three of its keys carry different codes.

| Row | ANSI | ISO |
|---|---|---|
| Left shift row | 6 keys | **7 keys** — `NON_US_BSLH` added |
| Right tab row, last | `BSLH` | `PG_DN` |
| Right home row, last two | `RET`, `DEL` | `NON_US_HASH`, `RET` |
| Right shift row, last | `PG_DN` | `DEL` |

Totals move from 37/47/84 to **38/47/85**, so the right half's `col-offset`
moves from 37 to 38.

Those keycap assignments are not guessed. They were read out of the factory
v2.3.0 Left ISO image, which stores its two layers as a 6x21 grid of 4-byte
entries at `0x4aa4c` (Fn) and `0x4ac44` (base). The same table also settles
this port's previously uncertain bottom row: the factory map is
`Fn / Control / Option / Command` from the outside in, exactly what the ANSI
keymap already carried as a guess.

## The left shift row, confirmed

The extra ISO key sits where reading order puts it. That was an assumption while
this port was written and is now confirmed on hardware (2026-08-22): the owner
typed the row through and `<`, `y`, `x`, `c`, `v`, `b` all land correctly.

```
pca24 bit 0 = LSHFT   bit 1 = NON_US_BSLH   bit 2 = Z   ...   bit 6 = B
```

So the left shift row is wired like every other row on this board, and the ISO
board does not reuse the ANSI wiring with the extra switch appended.

Recorded because the alternative was plausible and cheap to get wrong: it would
have shifted all six keys after left shift by one position, with left shift
typing `<`. If that symptom ever appears after a rewiring or a different board
revision, the fix is the shift row of the transform in `nocfree_and.dtsi` --
move `RC(0,27)` from second place to last -- plus the matching entry in
`tests/ansi_spec.py`. Nothing else changes.
