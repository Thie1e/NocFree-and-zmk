<!-- SPDX-License-Identifier: MIT -->

# Backlight

Driven on **P0.20**, one PWM channel, **active high** (`PWM_POLARITY_NORMAL`).

The pin is not new information: section 4 of the porting guide in the
repository README publishes it as `D5` on both halves. What this port was
missing was confidence in the polarity, which is why the baseline left the
backlight out. That is now resolved from two independent directions.

## The pin

The porting guide gives `Keyboard backlight | D5 | P0.20` for the left and
right controllers alike.

The factory v2.3.0 images agree. Their PWM driver configures exactly one
channel:

```
0002ba9a  ldr.w ip, [pc, #0x74]    ; -> 0x200088a8   (RAM: the PWM pin)
0002baae  ldr.w r7, [ip]
0002bab2  str.w r7, [r3, #0x560]   ; PSEL.OUT[0] = that pin
0002bab6  str.w r0, [r3, #0x564]   ; PSEL.OUT[1] = 0xFFFFFFFF (disconnected)
0002baba  str.w r0, [r3, #0x568]   ; PSEL.OUT[2] = disconnected
0002babe  str.w r0, [r3, #0x56c]   ; PSEL.OUT[3] = disconnected
```

and the RAM word is written in exactly one place:

```
0002bc0c  ldr r2, [pc, #8]     ; = 0x0004a694     (g_ADigitalPinMap)
0002bc10  ldr r2, [r2, #0x14]  ; index 5          (= D5)
0002bc12  str r2, [r3]
```

`0x4a694` is the variant's `g_ADigitalPinMap[]` — `pinMode()` at `0x45d24`
bounds-checks against `#0x10`, indexes this array, picks `P0` or `P1` from the
result and writes `PIN_CNF`. Reading it out reproduces the porting guide's
whole alias table, which is what makes it trustworthy:

| Alias | Left | Right | Published function |
|---|---|---|---|
| D0 | P0.10 | P0.05 | blue status LED (L) / PCA9555 INT (R) |
| D1 | P0.31 | P0.15 | PCA9555 INT (L) |
| D2 | P0.15 | P0.09 | BLE position detect (L) |
| D3 | P0.17 | P0.10 | 2.4 GHz position detect (L) |
| D4 | P0.09 | P0.17 | red charge / low-battery indicator |
| **D5** | **P0.20** | **P0.20** | **keyboard backlight** |
| D6 | P0.11 | P0.11 | I²C SDA |
| D7 | P1.09 | P1.09 | I²C SCL |
| D15 | P0.04 | P0.04 | battery ADC |
| D16 | P0.05 | P0.31 | battery-divider enable |

Every published alias matches. The Dongle image contains no PWM reference at
all, consistent with it having no backlight.

## Polarity

**Active high**, established on hardware on 2026-08-22.

This port first shipped the channel as `PWM_POLARITY_INVERTED`, reasoning from
the porting guide's note that the factory brightness API "drives the pin low at
endpoint value `255`", and from the factory PWM setup — the duty word is
`COUNTERTOP * brightness / 255`, masked with `ubfx r3, r3, #0, #15` so the
sequence word's polarity bit is clear.

That reasoning was wrong. On hardware the backlight was lit at brightness 0 and
got *dimmer* as the level rose: the scale ran backwards. Whatever the factory
firmware's compare-value convention means in its own terms, it does not
translate into an inverted Zephyr channel here. `PWM_POLARITY_NORMAL` is
correct.

The guide asks porters to verify this on hardware, and it was right to. The
failure mode was inverted light, not damage: P0.20 has no alternate silicon
function on the nRF52833 — no NFC, no reset, no analog input.

Note the consequence of getting it wrong: with the channel inverted, brightness
0 held the pin high, so `CONFIG_ZMK_BACKLIGHT_ON_START=n` produced a backlight
that was on at *full* from boot and could not be switched off. If a future
change makes the backlight behave inversely to the setting, this is the line to
look at first.

## Configuration

`CONFIG_ZMK_BACKLIGHT_ON_START=n`. `F5` sets 0 %, `F6` sets 60 %.

**Only absolute levels are bound, deliberately.** ZMK relays the backlight
behaviour to the peripheral (`BEHAVIOR_LOCALITY_GLOBAL` in
`behavior_backlight.c`) but never synchronises the resulting state: a search for
`backlight` across `app/src/split/` and `app/include/zmk/split/` returns
nothing, and each half persists its own `struct backlight_state` to its own NVS.
`zmk_backlight_calc_brt()` adds a *relative* step to whatever that half happens
to hold, so a single relay lost to a split-link hiccup leaves a permanent
brightness offset between the halves that survives reboots. `BL_SET` lands both
on the same number and clears it. `BL_INC`/`BL_DEC` are therefore not bound at
all.

This is not specific to this keyboard: every split ZMK board with a backlight
has it. Worth reporting upstream.

## The two halves are not equally bright

They do not reach the same brightness at the same duty, and there are two
separate reasons.

**Supply voltage.** A half on USB is visibly brighter than one on battery. Its
LEDs sit behind a regulated rail either way, but not at the same voltage, and
nothing in the PWM duty compensates. This part of the difference moves with the
battery's state of charge, so no fixed correction can remove it.

**The LED string itself.** With *both* halves on USB the right one is still
dimmer than the left. That residue is a property of the hardware -- LED count,
series resistors, or binning -- and it is constant, so it can be corrected.

ZMK has no per-half brightness adjustment: `zmk_backlight_update()` sends the
same value to whatever device `chosen { zmk,backlight }` names, and Zephyr's
`pwm-leds` binding has no scaling property (`led_pwm` computes
`pulse = period * brt / 100`). The correction therefore lives in a LED device of
this module's own, `nocfree,scaled-led`, which multiplies the brightness by a
fixed percentage and forwards to the real `pwm-leds` device. `chosen` points at
the scaled device, so ZMK talks to it without knowing.

Each half sets its own figure at the end of its board `.dts`:

```dts
&backlight {
    scale-percent = <70>;
};
```

100 forwards unchanged; below 100 dims that half; above 100 brightens it, with
the result clamped at 100 so a scale over 100 compresses the top of the range
rather than extending it.

The scaling rounds to nearest rather than down, which matters only at the very
bottom: brightness is an integer percentage, so with truncation any scale below
`100 / brt` would land on zero and switch that half off instead of running it at
its dimmest step. Zero in is still zero out.

**Both ends of the range are reachable, and both are end stops.** The LED API
carries brightness as an integer 0..100, so the dimmest non-zero output the chain
can produce is 1 and the brightest is 100. At the keymap's `BL_SET 60` those are
reached at `scale-percent = <1>` (60 x 1 % rounds to 1) and at
`scale-percent = <167>` (60 x 167 % clamps to 100). Below the first and above the second, changing
the figure does nothing at all.

Going dimmer than the floor needs either a lower `BL_SET` level in the keymap --
which moves both halves -- or a driver that writes the PWM directly and so can go
below one percent duty. There is nothing above the ceiling: if the half that is
already at full duty still looks dimmer, that residue is hardware, and the only
remaining lever is to bring the other half down to meet it.

**These numbers are tuned by eye and are not measurements.** Adjust the one
number on either half until the two match at the same setting, and tune for the
configuration you actually use -- for a left half on USB and a right on battery,
calibrate in that state.

Current figures: **left 25, right 30.** The right half sat at 100 until
2026-09-06, then went 100 -> 95 -> 80 -> 30, each step flashed and looked at
before the next. 95 was not a visible change at all, which is the useful
calibration point here: on this half a 5 % step is below the threshold of
noticing, so move it in steps of 15 or 20. Every one costs a flash of the
expensive half -- see the flashing notes.

The two figures now sit close together, which does **not** mean the halves are
equally bright at the same duty. They are not, and that asymmetry is the whole
reason this property exists.

## PWM frequency: 200 Hz, and why it went down rather than up

The channel runs at `PWM_MSEC(5)`. Both neighbours were tried first.

At low duty the left half emits a faint whine whenever the backlight is on. That
is not the LED: a multilayer ceramic capacitor is piezoelectric, so a current
that steps at an audible rate flexes it and the board radiates the result. Duty
is part of it -- at 100 % the current is constant and nothing is excited, which
is why the right half was silent for as long as it ran at full duty. It no
longer does: it was taken to 95 on 2026-09-06, so it is pulsed too now, and the
same hum may appear there. At 95 % the off-time is a twentieth of the period,
so the excitation is far weaker than anything that made the left half audible.

**Faster does not work.** `PWM_USEC(40)` -- 25 kHz, above hearing -- silences it
completely and stops the left half going dim. The duty ratio is not the reason:
the driver programs 160 of 16000 ticks at 1 kHz and 6 of 640 at 25 kHz,
prescaler 0 in both cases, 1.0 % against 0.94 %. That was read out of the
generated `zephyr.dts` and `pwm_nrfx_set_cycles`, not assumed. What changes is
the shape of the pulse: the LED stage has a fixed turn-off tail, and a tail that
is negligible beside a 1 ms cycle is a large part of a 40 us one, so the same
nominal duty puts out far more light. **The PWM rate sets how dim this backlight
can go, and raising it raises the floor.**

**A longer duty does not work either.** 3 % and 4 % were both audible, and 20 %
had already been rejected as too bright, so there is no window between the two.

That leaves down. 200 Hz keeps everything the fast rate destroyed -- a 5 ms
period leaves the turn-off tail as insignificant as 1 ms did, so the dim end
survives -- while moving the tone to where a small ceramic radiates poorly and
the ear is less sensitive. Loudness is not linear in frequency for a radiator
this size; the drop from 1 kHz to 200 Hz is much larger than the ratio suggests.

The cost is the phantom-array effect. 200 Hz is far above flicker fusion, so the
backlight looks steady, but a pulsed LED can break into a row of dots during a
saccade, and low duty makes that more visible, not less. If that shows up, the
rate has to come back up and the whine with it.

`tests/test_board_definition.py` holds the period between 500 us and 20 ms --
slow enough to dim, fast enough not to flicker outright -- so the 25 kHz
experiment cannot be repeated by accident.

## Not done here

Battery reporting stays off. Its pins are published too (D15/D16), but this
port has still not verified the divider on hardware, and the guide is explicit
that the divider must be disabled after sampling. That is a separate change
with its own risk; see [limitations.md](limitations.md).
