<!-- SPDX-License-Identifier: MIT -->

# Notes for coding agents

This file is for LLM-based assistants working in this repository. Humans may
prefer [README.md](README.md) and `docs/`, which this file does not duplicate.

`CLAUDE.md` is a symlink to this file.

## What this repository is

A fork of [NocFreeKB/NocFree-and-zmk](https://github.com/NocFreeKB/NocFree-and-zmk)
adding ISO layout support, a backlight and bootloader keys. There is also a
battery readout, but it is an acknowledged stub -- see below.
It is a **ZMK module**, not a ZMK fork: Zephyr and ZMK are pulled in by `west`
at a pinned revision, and this repository only carries board definitions,
devicetree, two small drivers and tests.

The hardware is a split keyboard whose halves are **not equal**. The left half
is the ZMK split central: it holds the keymap, the layers, BLE and USB. The
right half is a scanner that ships key *positions* and knows nothing about what
they mean. Almost every "why is it like this" question resolves to that.

## Ground rules

**`README.md` contains NocFree's porting guide, which is not ours to edit.**
Our own content is the section above the `---` separator; everything below it is
upstream's document, reproduced intact. `tests/test_repository_hygiene.py`
asserts its headings and several of its hardware facts still stand. If a fact in
that guide turns out to be wrong on real hardware, record the correction in
`docs/`, not by editing the guide.

**Section 4 of that guide has the full pin map.** I2C, expander addresses and
port order, backlight, status LEDs, battery ADC and divider enable, and the
nRF24L01 lines. Read it before disassembling anything or inferring a pin. This
has been learned the hard way more than once.

**`tests/ansi_spec.py` is the single source of truth for the key matrix.** Key
counts, the transform and the default layer are derived from it. Change that
file first and the rest of the suite follows; change a board file alone and the
tests will tell you off.

**Never claim a hardware behaviour you have not seen.** Much of `docs/` exists
because a plausible inference was wrong: the backlight polarity, the PWM rate's
effect on brightness, the battery divider ratio, and the cause of a
"broken" bootloader key were all wrong on first reasoning and right only after
someone looked at the device. Mark what is measured, what is inferred, and what
is a guess.

**One observation is not a calibration.** The battery divider is the cautionary
tale, and it is still in the tree: a ratio was derived from a single reading of
a full cell, written up as "calibrated on hardware", and guarded with a test --
and it was wrong, because the anchor point sat at the top of the range where a
saturated reading and a correct one are indistinguishable. Do not write a test
that pins a physical constant to one measurement, and do not let a docstring
claim more confidence than the observation supports. See
[docs/battery.md](docs/battery.md).

**The battery readout is a stub and is staying that way.** `Fn`+`i` types
`bat NN`; the number reads 100 permanently on the unit it was written for. Do
not present it as working, and do not start calibrating it unless someone asks
-- the owner has explicitly said they do not need it. The reusable part is the
behaviour that types a runtime integer as keystrokes.

## Things that will cost you an hour if you rediscover them

**A module does not inherit ZMK's include path.** ZMK adds `app/include` to its
own target as `PRIVATE`, so `drivers/behavior.h` does not resolve from module
sources. `CMakeLists.txt` adds it back through `${APPLICATION_SOURCE_DIR}/include`
— ZMK is the Zephyr application here, so that is `zmk/app`. Not
`${ZEPHYR_ZMK_MODULE_DIR}`, which is empty.

**`io-channels` takes the bare AIN number**, `<&adc 2>` for AIN2.
`battery_voltage_divider.c` computes `AnalogInput0 + channel` itself, so passing
the `NRF_SAADC_AIN2` constant (which is 3) selects the wrong input and gives a
plausible-looking wrong voltage.

**The battery divider node must stay per-half.** The ADC pin is the same on both
halves but the enable line is not (`P0.05` left, `P0.31` right), so a node in
the shared `.dtsi` drives the wrong pin on one of them.

**Raising the PWM frequency raises the brightness floor on this hardware.** The
LED stage has a fixed turn-off tail: negligible in a 1 ms period, a large share
of a 40 us one, so the same duty emits far more light. The rate is guarded from
both sides in the tests. If you are here to silence the coil whine, the lever is
*duty*, not rate. See [docs/backlight.md](docs/backlight.md).

**Backlight state is not synced between halves.** ZMK's backlight behaviour is
global and each half keeps its own state in its own NVS, so one missed relay
puts a permanent offset between them and relative steps preserve it forever.
Only absolute levels (`BL_SET`) are drift-proof. Do not add a `BL_INC`/`BL_DEC`
binding.

**`scale-percent` above 100 is a silent no-op.** Duty saturates; a larger figure
produces a bit-identical image. Either half can only be taken *down*. A test
guards this.

**`.uf2` is not a flat image.** 512-byte blocks with 32-byte headers. Running
`strings` or `grep` over one yields garbage and silently corrupts anything
crossing a block boundary.

## Physical constraints on your suggestions

**Flashing the right half is expensive.** It needs both halves cabled — the left
because it runs the keymap and relays the behaviour over the split link, the
right because its bootloader presents a USB mass-storage device and a device
needs a host to enumerate to. Say explicitly which halves a change requires.
Keymap and left-half changes never need it.

**The left half is at about 95 % of its 248 KiB code partition.** Check the
build output before proposing a feature that lands there. If it does not fit,
that is the constraint to report, not something to squeeze past.

**The nRF52833's USB is device-only.** There is no host controller in the
silicon, so the halves cannot be wired to each other over USB no matter what
firmware does. A genuinely wired split would need UART between them.

**Brightness and comfort settings are tuned by eye.** When one is being tuned,
change one number per build and ask for a reading before the next. Do not ship a
fan of variants for someone to sort out.

## Before you finish

```sh
./scripts/build-local.sh /tmp/nocfree-build    # Docker; ~3.1 GB, keep it out of the repo
NOCFREE_BUILD_DIR=/tmp/nocfree-build/build ./tests/run.sh
```

Without `NOCFREE_BUILD_DIR` the artifact tests **skip**, which has hidden a
stale assertion before. Run them against a real build whenever you change
Kconfig or devicetree.

The Docker build writes as root; remove the workspace through a container
(`docker run --rm -v /tmp:/t alpine rm -rf /t/nocfree-build`) rather than
puzzling over permission errors.

Devicetree changes are worth verifying in the generated `zephyr.dts` — values
appear there in hex, so `scale-percent = <30>` reads back as `< 0x1e >`.
