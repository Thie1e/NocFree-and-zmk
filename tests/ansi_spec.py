# SPDX-License-Identifier: MIT
"""The single source of truth for the NocFree & ISO key map.

Everything the tests assert about the devicetree, the keymap and the built
artifacts is derived from this file, so a change to the board has to be made
here as well as in the devicetree before the suite will pass.
"""

from __future__ import annotations

# The six logical scan rows, in the port order NocFree publishes:
#   0x20/P0, 0x20/P1, 0x22/P0, 0x22/P1, 0x24/P0, 0x24/P1
# Expander pins 0-7 are port 0 and pins 8-15 are port 1.
ROWS = [
    ("pca20", 0),
    ("pca20", 8),
    ("pca22", 0),
    ("pca22", 8),
    ("pca24", 0),
    ("pca24", 8),
]

EXPANDER_ADDRESSES = {"pca20": 0x20, "pca22": 0x22, "pca24": 0x24}

# Populated inputs per row. These are the key counts of an ISO board split
# between T and Y; every other expander bit is an unpopulated position.
#
# ISO carries one key more than ANSI: the NON_US_BSLH key between the left
# shift and Z. It is the seventh input of the left half's shift row, so that
# row reads seven inputs rather than ANSI's six. The right half is
# electrically identical to ANSI -- only three of its keycaps differ.
#
# The bit order within that row is the one open assumption in this file:
# every other row on this board is wired in reading order, so the ISO key is
# taken to be bit 1 (between LSHFT and Z). If the ISO board instead reuses
# the ANSI wiring with the extra switch appended, the key is bit 6 and the
# six keys after LSHFT will read one position to the left. See
# docs/iso-de.md for the one-line correction and how to tell.
LEFT_COUNTS = [7, 7, 6, 6, 7, 5]
RIGHT_COUNTS = [8, 8, 8, 8, 8, 7]

LEFT_KEYS = sum(LEFT_COUNTS)    # 38
RIGHT_KEYS = sum(RIGHT_COUNTS)  # 47
TOTAL_KEYS = LEFT_KEYS + RIGHT_KEYS  # 85

RIGHT_COL_OFFSET = LEFT_KEYS

# All sixteen pins of a PCA9555.
ALL_BITS = set(range(16))


def key_inputs(counts: list[int]) -> list[tuple[str, int]]:
    """(expander, bit) for each KSCAN column, in column order."""
    out: list[tuple[str, int]] = []
    for (label, base), count in zip(ROWS, counts):
        out.extend((label, base + i) for i in range(count))
    return out


LEFT_INPUTS = key_inputs(LEFT_COUNTS)
RIGHT_INPUTS = key_inputs(RIGHT_COUNTS)


def unused_bits(counts: list[int]) -> dict[str, set[int]]:
    """Expander bits that must NOT appear in a half's key-inputs list."""
    used: dict[str, set[int]] = {label: set() for label, _ in ROWS}
    for label, bit in key_inputs(counts):
        used[label].add(bit)
    return {label: ALL_BITS - bits for label, bits in used.items()}


LEFT_UNUSED = unused_bits(LEFT_COUNTS)
RIGHT_UNUSED = unused_bits(RIGHT_COUNTS)


def transform_positions() -> list[int]:
    """The transform map, in visual reading order: left row then right row."""
    out: list[int] = []
    left, right = 0, RIGHT_COL_OFFSET
    for lc, rc in zip(LEFT_COUNTS, RIGHT_COUNTS):
        out.extend(range(left, left + lc))
        out.extend(range(right, right + rc))
        left += lc
        right += rc
    return out


TRANSFORM = transform_positions()

# The default layer, in the same visual order as TRANSFORM. Row boundaries
# follow LEFT_COUNTS/RIGHT_COUNTS.
DEFAULT_LAYER = [
    # Function row. F5..F12 carry the owner's media and backlight functions
    # directly, the way the factory firmware did; the real F-keys live on the
    # Fn layer. The last position was deliberately disabled: Page Up and Page
    # Down are reachable as Fn+Home and Fn+End, so they do not need a key of
    # their own here.
    "kp ESC", "kp F1", "kp F2", "kp F3", "kp F4", "bl BL_SET 0", "bl BL_SET 100",
    "kp C_PREV", "kp C_PP", "kp C_NEXT", "kp C_MUTE", "kp C_VOL_DN", "kp C_VOL_UP",
    "kp PSCRN", "none",
    # Number row
    "kp GRAVE", "kp N1", "kp N2", "kp N3", "kp N4", "kp N5", "kp N6",
    "kp N7", "kp N8", "kp N9", "kp N0", "kp MINUS", "kp EQUAL", "kp BSPC", "kp HOME",
    # Tab row
    "kp TAB", "kp Q", "kp W", "kp E", "kp R", "kp T",
    "kp Y", "kp U", "kp I", "kp O", "kp P", "kp LBKT", "kp RBKT", "kp END",
    # Home row
    "kp CAPS", "kp A", "kp S", "kp D", "kp F", "kp G",
    "kp H", "kp J", "kp K", "kp L", "kp SEMI", "kp SQT", "kp NON_US_HASH", "kp RET",
    # Shift row
    "kp LSHFT", "kp NON_US_BSLH", "kp Z", "kp X", "kp C", "kp V", "kp B",
    "kp N", "kp M", "kp COMMA", "kp DOT", "kp FSLH", "kp RSHFT", "kp UP", "kp DEL",
    # Bottom row, as the owner arranged it in NocFree Link: Control outermost
    # on the left, AltGr right of space, Fn between the two right-hand mods.
    "kp LCTRL", "mo 1", "kp LGUI", "kp LALT", "kp SPACE",
    "kp SPACE", "kp RALT", "mo 1", "kp RCTRL", "kp LEFT", "kp DOWN", "kp RIGHT",
]

# Flash geometry, from the two public Adafruit linker scripts. See
# docs/architecture.md for the citation.
PARTITIONS = {
    "sd_partition": (0x00000000, 0x00027000),
    "code_partition": (0x00027000, 0x0003E000),
    "storage_partition": (0x00065000, 0x00008000),
    "boot_partition": (0x00074000, 0x0000C000),
}
READ_ONLY_PARTITIONS = {"sd_partition", "boot_partition"}
FACTORY_FILESYSTEM = (0x0006D000, 0x00074000)
FLASH_END = 0x00080000
