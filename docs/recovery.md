<!-- SPDX-License-Identifier: MIT -->

# Recovery

Read NocFree's disclaimer in the [repository README](../README.md) first.
Flashing community firmware is an unofficial modification carried out at your
own risk.

## What this firmware preserves

The application is linked and flashed only into `0x27000..0x64FFF`, with its
settings in `0x65000..0x6CFFF`. The SoftDevice region, the factory filesystem at
`0x6D000..0x73FFF` and the bootloader region at `0x74000..0x7FFFF` are declared
read-only in the devicetree and are never written. The vendor rollback path is
intended to stay intact.

Confirm the layout before you flash anything: put the half into its bootloader,
open the mass-storage volume that appears, and read `INFO_UF2.TXT`. If the
reported application start address is not `0x27000`, **stop** — this firmware's
partition map does not describe your device, and flashing it could overwrite
something that is not the application.

## Getting into the bootloader

Two routes, in order of preference.

**1. 1200-baud touch (both halves).** Both images expose a USB CDC serial
interface. Opening it at 1200 baud requests a warm reset into the preserved UF2
bootloader. This is the same convention Arduino and Adafruit tooling use.

```sh
# Linux -- resolves the port itself, so it does not matter which ttyACM
# number the kernel handed out. Connect one half at a time.
sudo stty -F "$(readlink -f /dev/serial/by-id/*NocFree*)" 1200

# macOS
stty -f /dev/tty.usbmodemXXXX 1200
```

On Linux the CDC node is owned by `root:dialout`, so this needs `sudo` unless
the user is in the `dialout` group. `usermod -aG dialout "$USER"` and a fresh
login removes that, or a udev rule scoped to the ZMK vendor/product ID
(`1d50:615e`) does the same for this keyboard alone.

**2. `Fn`+`Esc` and `Fn`+`Delete` (key combination).** Both are hold-taps: a
tap resets that half, a 1.5-second hold reboots it into its bootloader. ZMK
reset behaviours act on the half whose key triggered them, and `Esc` is a
left-half key while `Delete` is a right-half one, so `Fn`+`Esc` recovers the
left half and `Fn`+`Delete` the right.

**Both are confirmed working on hardware.** `Fn`+`Delete` carries one condition
that is easy to mistake for a fault: **the right half must be connected to USB
itself.** The bootloader presents a mass-storage device, and a device needs a
host to enumerate to, so on an uncabled half the reset happens and the drive
simply never appears. Flashing the right half therefore wants **both** halves
cabled — the left because it runs the keymap and forwards the behaviour over the
split link, the right because that is where the drive has to show up.

`Fn`+`Delete` also only works while the right half is connected to the left over
the split link. A right half that cannot pair — the main recovery scenario —
must use the 1200-baud touch, which is exactly why it carries the CDC interface.

### Telling the halves apart

`Board-ID` is `NocFree &` on both, so the bootloader drive does not identify
which half you are on. The CDC serial node does:

```sh
ls -l /dev/serial/by-id/
# ...NocFree___<serial>-if00        -> left
# ...NocFree___Right_<serial>-if00  -> right
```

### Notes from diagnosing this

Recorded because it took a USB-logging build to settle, and none of it should
need re-deriving. Checked against ZMK `6e2ef41` and against the built images:

- `&bootloader` is `BEHAVIOR_LOCALITY_EVENT_SOURCE`, and `behavior.c` sends
  non-local sources to `zmk_split_central_invoke_behavior`.
- Hold-tap preserves `.source` into every one of its four binding calls.
- The name `bootload` is 8 characters and fits `ZMK_SPLIT_RUN_BEHAVIOR_DEV_LEN`
  (9), and the peripheral's lookup falls back to `strcmp`, so it resolves.
- The behaviour is genuinely built into the right-half image: its device struct
  is well formed and its config byte is `0x01` (`BOOT_MODE_TYPE_BOOTLOADER`),
  byte-identical to the left half's.
- Both halves set `CONFIG_RETENTION_BOOT_MODE=y` and pull in the same
  `nrf52833_uf2_boot_mode.dtsi`, so the boot-mode plumbing is symmetric.
- The payload is 20 bytes and the central writes it in one
  `bt_gatt_write_without_response`, fitting the default 23-byte ATT MTU with
  `offset == 0`. (`split_svc_run_behavior` does `memcpy(payload + offset, ...)`,
  which advances by whole structs rather than bytes — a genuine upstream bug,
  but dormant while the write is not fragmented.)

To build a peripheral image that logs over CDC, `CONFIG_ZMK_USB_LOGGING=y` is
not sufficient on this board: Zephyr's UART log backend resolves its device from
the `zephyr,console` chosen node at compile time, and this board deliberately
declares `cdc_acm_uart0` without designating it as console. A devicetree overlay
adding `zephyr,console = &cdc_acm_uart0` is required, passed via
`-DEXTRA_DTC_OVERLAY_FILE=` — dropping it into the ZMK config directory alone is
ignored. Expect the right-half image to grow from roughly 76 % to 90 % of the
code partition, and expect `Unable to enable USB` in the log, which is harmless:
the board already enumerates USB via `CONFIG_USB_DEVICE_INITIALIZE_AT_BOOT`.

## Order of operations

Flash the **left** half first, and prove recovery on it before touching the
right.

The left half presents USB HID, so it is the only half whose scanner, keymap and
boot behaviour you can verify on its own. More importantly, it is where you can
confirm that 1200-baud touch actually returns a half to the bootloader. Once
that is demonstrated, flashing the right half — whose only recovery path that
does not depend on a working split link is that same mechanism — is a known
quantity rather than a bet.

1. Flash the left half.
2. Verify it boots, enumerates, and types over USB.
3. Trigger 1200-baud touch and confirm the bootloader volume returns.
4. Re-flash the left half, then flash the right.

## Stop conditions

Stop and reassess if any of these occur.

- `INFO_UF2.TXT` reports an application start address other than `0x27000`.
- The bootloader volume does not appear, or a different device appears than the
  one you were targeting.
- A flashed half does not enumerate over USB at all.
- Any key reports as continuously held.
- A half becomes noticeably warm.
- You no longer have a way back into the bootloader on either half.

## Returning to factory firmware

Obtain the correct role-specific factory image through NocFree's official
channel. This repository does not redistribute vendor firmware and cannot
verify it for you.

This firmware leaves unused bytes in the tail of the application region after a
rollback. They are unreachable from the factory application, and leaving them is
preferable to writing over the factory filesystem.
