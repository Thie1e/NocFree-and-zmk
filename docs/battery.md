<!-- SPDX-License-Identifier: MIT -->

# Battery

## Why the level is typed out

USB HID has no battery channel. A level published as a BLE Battery Service is
measured but invisible to a host on a cable, and this keyboard is used wired,
so a readout that is only visible over Bluetooth is a readout nobody sees.

The factory firmware reached the same conclusion and typed a status line out as
keystrokes. `Fn`+`i` here does the same thing, on the same key.

## Measurement

Section 4 of NocFree's porting guide publishes the pins:

| | left | right |
|---|---|---|
| Battery ADC | D15 = `P0.04` (AIN2) | D15 = `P0.04` (AIN2) |
| Divider enable | D16 = `P0.05` | D16 = `P0.31` |

The enable line is the one that differs, which is why the divider node lives in
each board's `.dts` rather than the shared `.dtsi`.

Section 5 adds a 12-bit ADC and a `130/100` scale factor, and requires the
divider to be disabled after sampling to avoid continuous current. ZMK's
`zmk,battery-voltage-divider` does all of that: it drives `power-gpios` high
before sampling and low afterwards, and configures resolution, oversampling and
calibration itself. No driver code was needed.

The ohms encode the ratio, not real resistances -- the driver only ever uses
`full-ohms / output-ohms`.

The devicetree says `150/100`, not the `130/100` the guide publishes. **Read
the next section before trusting either number** -- that change was made on one
observation and did not survive contact with the hardware.

Two notes on `io-channels`:

- It takes the bare AIN number (`<&adc 2>`). `battery_voltage_divider.c`
  computes `AnalogInput0 + channel` itself, so the `NRF_SAADC_AIN2` constant
  (which is 3) would select the wrong input.
- The SAADC is enabled in the shared `.dtsi`; only the divider is per-half.

## This reading is a stub, and here is how it went wrong

**Do not trust the number.** On the unit this was written for it reads `bat 100`
permanently. It has never been observed falling.

The story is worth keeping, because the mistake is an easy one:

1. With the guide's `130/100`, a battery the owner reported as full read
   `bat 26`. That is about 3.64 V where a charged cell sits at 4.20 V, so the
   ratio looked wrong.
2. Working back from the 2.80 V that implies at the pin gave `4200/2801 = 1.500`
   -- a round number of the kind a real resistor pair produces. `150/100` went
   in, and a test was added to stop anyone restoring the documented value.
3. It then read `bat 100`. Permanently.

The arithmetic explains why. `lithium_ion_mv_to_pct()` clamps at 4200 mV, and
with a 1.5 ratio any pin voltage above 2.80 V saturates. **A cell on a charger
sits at or above that**, so the reading is pinned to the ceiling in exactly the
situation it was calibrated in. One anchor point, taken at the top of the range,
cannot distinguish "correctly reading a full battery" from "saturated".

So the earlier claim that the ratio *is* calibrated was wrong, and the test
guarding `150` guards a figure with one observation behind it. What can be said:
the measurement path works end to end -- the SAADC reads, the divider enable
switches, the digits get typed -- and the number responds to *something*. Which
of `130`, `150` or neither is right is unknown.

Fixing it properly needs a second anchor near empty, which means running the
keyboard down on battery and reading the value at a known cell voltage, and
probably replacing the linear curve. **Nobody is working on that**, and the
owner does not need it. It is left in as a worked example of typing a runtime
value out as keystrokes, which is the part that is genuinely reusable.

## The typed readout

`Fn`+`i` types `bat NN`.

It is a behaviour (`nocfree,behavior-battery-report`), not a macro. ZMK macros
send a sequence fixed at compile time; the percentage is a runtime integer, so
the digits have to be converted to keycodes and queued. It uses ZMK's own
behaviour queue, which handles the press/release timing.

**Output is restricted to digits, letters and space.** Keycodes are positional
and this keyboard types German ISO, where punctuation sits elsewhere than on
ANSI -- a `%` would type as some other character. That is why the line reads
`bat 87` and not `bat 87%`.

Leading zeros are suppressed, so 7 % types as `bat 7`.

If the shared behaviour queue is full the line is truncated rather than
retried. It is a status readout; blocking or dropping real keystrokes to
finish it would be the worse failure.

### Building a behaviour in this module

ZMK adds `app/include` to its own application target as `PRIVATE`, so a module
never inherits it and `drivers/behavior.h` will not resolve. `CMakeLists.txt`
adds it back via `APPLICATION_SOURCE_DIR`, which points at `zmk/app` because
ZMK is the Zephyr application here.

## Cost

The left image went from 93.1 % of the code partition to 94.62 %: roughly
1.2 points for the measurement and 0.3 for the typed readout.

## Not done, and not planned

**Calibration.** See above: it needs a discharge run and a second anchor point.

**The right half's level.** `CONFIG_ZMK_SPLIT_BLE_CENTRAL_BATTERY_LEVEL_PROXY`
reports peripheral levels through an extra battery service, and would need the
same devicetree work on the right board plus a flash of that half. The typed
line would then have to carry two numbers. Pointless until the left half's
number means something.
