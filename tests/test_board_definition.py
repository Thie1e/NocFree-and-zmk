#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Validate the board devicetree, keymap, metadata and configuration."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

import ansi_spec as spec

ROOT = Path(__file__).resolve().parents[1]
BOARD = ROOT / "boards/nocfree/nocfree_and"

LEFT_DTS = BOARD / "nocfree_and_left_nrf52833_zmk.dts"
RIGHT_DTS = BOARD / "nocfree_and_right_nrf52833_zmk.dts"
SHARED_DTSI = BOARD / "nocfree_and.dtsi"
KEYMAP = BOARD / "nocfree_and.keymap"


def strip_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    return re.sub(r"//[^\n]*", " ", text)


def read(path: Path) -> str:
    return strip_comments(path.read_text())


def key_inputs(path: Path) -> list[tuple[str, int]]:
    body = re.search(r"key-inputs\s*=\s*(.*?);", read(path), re.S)
    assert body, f"no key-inputs in {path.name}"
    return [(label, int(bit)) for label, bit in re.findall(r"<&(\w+)\s+(\d+)>", body.group(1))]


def property_value(text: str, node: str, prop: str) -> str | None:
    match = re.search(rf"{re.escape(node)}\s*\{{(.*?)\n\}};", text, re.S)
    if not match:
        return None
    found = re.search(rf"\b{re.escape(prop)}\s*=\s*<([^>]*)>", match.group(1))
    return found.group(1).strip() if found else None


def _layer_bindings(keymap, layer):
    """Split one layer's bindings into individual behaviour invocations."""
    match = re.search(layer + r"\s*\{.*?bindings = <(.*?)>;", keymap, re.S)
    if match is None:
        raise AssertionError("layer not found: " + layer)

    out = []
    for part in re.split(r"(?=&)", match.group(1)):
        part = part.strip()
        if part:
            out.append(" ".join(part.split()))
    return out


class KeyInputTest(unittest.TestCase):
    """The exact expander bit each ANSI position is wired to."""

    def test_left_inputs_are_exact(self):
        self.assertEqual(key_inputs(LEFT_DTS), spec.LEFT_INPUTS)
        self.assertEqual(len(key_inputs(LEFT_DTS)), spec.LEFT_KEYS)

    def test_right_inputs_are_exact(self):
        self.assertEqual(key_inputs(RIGHT_DTS), spec.RIGHT_INPUTS)
        self.assertEqual(len(key_inputs(RIGHT_DTS)), spec.RIGHT_KEYS)

    def test_no_input_is_declared_twice(self):
        for path in (LEFT_DTS, RIGHT_DTS):
            with self.subTest(path.name):
                inputs = key_inputs(path)
                self.assertEqual(len(inputs), len(set(inputs)))

    def test_unpopulated_expander_bits_are_excluded(self):
        for path, unused in ((LEFT_DTS, spec.LEFT_UNUSED), (RIGHT_DTS, spec.RIGHT_UNUSED)):
            declared = set(key_inputs(path))
            for label, bits in unused.items():
                for bit in bits:
                    with self.subTest(f"{path.name} {label} bit {bit}"):
                        self.assertNotIn((label, bit), declared)

    def test_every_declared_bit_is_within_the_part(self):
        for path in (LEFT_DTS, RIGHT_DTS):
            for label, bit in key_inputs(path):
                with self.subTest(f"{path.name} {label} {bit}"):
                    self.assertIn(bit, spec.ALL_BITS)

    # Single-key resolution and the released state are exercised against the
    # real decoding code in tests/test_kscan_scan.c; re-deriving them here from
    # the same list the exactness tests above already pin would prove nothing.


class TransformTest(unittest.TestCase):
    def test_transform_is_the_full_ansi_order(self):
        body = re.search(r"matrix_transform0:.*?map\s*=\s*<(.*?)>;", read(SHARED_DTSI), re.S)
        self.assertIsNotNone(body)
        actual = [int(v) for v in re.findall(r"RC\(0,(\d+)\)", body.group(1))]
        self.assertEqual(actual, spec.TRANSFORM)
        self.assertEqual(sorted(actual), list(range(spec.TOTAL_KEYS)))

    def test_transform_dimensions_match_the_direct_input_model(self):
        text = read(SHARED_DTSI)
        self.assertEqual(property_value(text, "matrix_transform0: keymap_transform_0", "rows"), "1")
        self.assertEqual(
            property_value(text, "matrix_transform0: keymap_transform_0", "columns"),
            str(spec.TOTAL_KEYS),
        )

    def test_only_the_right_half_offsets_its_columns(self):
        self.assertRegex(read(RIGHT_DTS), rf"col-offset\s*=\s*<{spec.RIGHT_COL_OFFSET}>")
        self.assertNotIn("col-offset", read(LEFT_DTS))

    def test_offset_columns_stay_inside_the_transform(self):
        highest = spec.RIGHT_COL_OFFSET + spec.RIGHT_KEYS - 1
        self.assertEqual(highest, spec.TOTAL_KEYS - 1)


class KeymapTest(unittest.TestCase):
    def layers(self) -> dict[str, list[str]]:
        text = read(KEYMAP)
        out = {}
        for name, body in re.findall(r"(\w+_layer)\s*\{(.*?)\};", text, re.S):
            bindings = re.search(r"bindings\s*=\s*<(.*?)>;", body, re.S)
            if bindings:
                out[name] = [b.strip() for b in re.findall(r"&([^&<>]+)", bindings.group(1))]
        return out

    def test_every_layer_covers_every_position(self):
        layers = self.layers()
        self.assertIn("default_layer", layers)
        self.assertIn("function_layer", layers)
        for name, bindings in layers.items():
            with self.subTest(name):
                self.assertEqual(len(bindings), spec.TOTAL_KEYS)

    def test_default_layer_is_the_expected_ansi_map(self):
        self.assertEqual(self.layers()["default_layer"], spec.DEFAULT_LAYER)

    def test_recovery_and_output_bindings_are_reachable(self):
        function = self.layers()["function_layer"]
        for binding in ("boot_reset 0 0", "out OUT_USB", "out OUT_BLE", "bt BT_CLR"):
            with self.subTest(binding):
                self.assertIn(binding, function)

    def test_an_absolute_brightness_binding_exists(self):
        """ZMK relays the backlight behaviour to the peripheral but never
        synchronises the state, and BL_INC/BL_DEC are relative -- so a single
        lost relay leaves the two halves permanently unequal. Only BL_SET
        lands both on the same number. See docs/backlight.md."""
        bindings = [b for layer in self.layers().values() for b in layer]
        absolute = [b for b in bindings if b.startswith("bl BL_SET")]
        self.assertTrue(absolute, "no &bl BL_SET binding: brightness cannot be resynced")
        self.assertIn("bl BL_SET 0", absolute)
        self.assertTrue(any(b != "bl BL_SET 0" for b in absolute),
                        "an off-level alone cannot turn the backlight on")

    def test_each_half_can_reach_its_own_bootloader(self):
        """A reset behaviour only ever acts on the half whose key ran it, so
        every half needs its own. Tap resets, hold reaches the bootloader."""
        keymap = read(BOARD / "nocfree_and.keymap")
        self.assertIn('compatible = "zmk,behavior-hold-tap";', keymap)
        self.assertIn("bindings = <&bootloader>, <&sys_reset>;", keymap)
        self.assertIn("tapping-term-ms = <1500>;", keymap)

        function = self.layers()["function_layer"]
        left = [function[i] for i, p in enumerate(spec.TRANSFORM)
                if p < spec.RIGHT_COL_OFFSET]
        right = [function[i] for i, p in enumerate(spec.TRANSFORM)
                 if p >= spec.RIGHT_COL_OFFSET]
        with self.subTest("left"):
            self.assertIn("boot_reset 0 0", left)
        with self.subTest("right"):
            self.assertIn("boot_reset 0 0", right)

    def test_a_function_key_exists_on_both_halves(self):
        """Bluetooth pairing and recovery are only reachable through Fn."""
        default = spec.DEFAULT_LAYER
        left = [default[i] for i, p in enumerate(spec.TRANSFORM) if p < spec.RIGHT_COL_OFFSET]
        right = [default[i] for i, p in enumerate(spec.TRANSFORM) if p >= spec.RIGHT_COL_OFFSET]
        self.assertIn("mo 1", left)
        self.assertIn("mo 1", right)


class FlashLayoutTest(unittest.TestCase):
    """The bootloader, SoftDevice and factory filesystem must stay untouched."""

    def partitions(self) -> dict[str, tuple[int, int, bool]]:
        text = SHARED_DTSI.read_text()
        block = re.search(r"&flash0\s*\{(.*)\n\};", text, re.S)
        assert block
        out = {}
        for label, body in re.findall(r"(\w+):\s*partition@\w+\s*\{(.*?)\}", block.group(1), re.S):
            reg = re.search(r"reg\s*=\s*<\s*(0x[0-9a-fA-F]+)\s+(0x[0-9a-fA-F]+)\s*>", body)
            assert reg, label
            out[label] = (int(reg.group(1), 16), int(reg.group(2), 16), "read-only" in body)
        return out

    def test_partition_bounds_are_exact(self):
        found = self.partitions()
        for label, (start, size) in spec.PARTITIONS.items():
            with self.subTest(label):
                self.assertIn(label, found)
                self.assertEqual(found[label][0], start)
                self.assertEqual(found[label][1], size)

    def test_softdevice_and_bootloader_are_read_only(self):
        found = self.partitions()
        for label, (_, _, read_only) in found.items():
            with self.subTest(label):
                self.assertEqual(read_only, label in spec.READ_ONLY_PARTITIONS)

    def test_writable_regions_never_reach_the_factory_filesystem(self):
        found = self.partitions()
        fs_start, fs_end = spec.FACTORY_FILESYSTEM
        for label in ("code_partition", "storage_partition"):
            start, size, _ = found[label]
            with self.subTest(label):
                self.assertLessEqual(start + size, fs_start)

        self.assertEqual(found["boot_partition"][0], fs_end)
        self.assertEqual(
            found["boot_partition"][0] + found["boot_partition"][1], spec.FLASH_END
        )

    def test_no_partition_overlaps_another(self):
        ranges = sorted((start, start + size) for start, size, _ in self.partitions().values())
        for (_, end), (next_start, _) in zip(ranges, ranges[1:]):
            self.assertLessEqual(end, next_start)

    def test_the_application_links_into_the_code_partition(self):
        self.assertIn("zephyr,code-partition = &code_partition;", read(SHARED_DTSI))
        for path in (
            BOARD / "nocfree_and_left_nrf52833_zmk_defconfig",
            BOARD / "nocfree_and_right_nrf52833_zmk_defconfig",
        ):
            with self.subTest(path.name):
                self.assertIn("CONFIG_USE_DT_CODE_PARTITION=y", path.read_text())


class BusTest(unittest.TestCase):
    def test_expanders_are_declared_at_the_published_addresses(self):
        pattern = r"(\w+):\s*keys@\w+\s*\{[^}]*?reg\s*=\s*<(0x\w+)>"
        found = {
            label: int(addr, 16)
            for label, addr in re.findall(pattern, read(SHARED_DTSI), re.S)
        }
        self.assertEqual(found, spec.EXPANDER_ADDRESSES)

    def test_bus_uses_the_conservative_standard_mode(self):
        self.assertRegex(read(SHARED_DTSI), r"clock-frequency\s*=\s*<I2C_BITRATE_STANDARD>")

    def test_active_scan_period_exceeds_the_bus_transfer_time(self):
        """A scan that cannot finish inside its own period never idles.

        One two-byte port-pair read is about 48 bit times plus framing. At
        100 kHz that is ~0.5 ms per expander, so three expanders need ~1.5 ms.
        """
        bit_time_us = 1_000_000 / 100_000
        per_expander_us = 48 * bit_time_us
        scan_ms = (per_expander_us * len(spec.EXPANDER_ADDRESSES)) / 1000

        for path in (LEFT_DTS, RIGHT_DTS):
            text = read(path)
            active = int(re.search(r"debounce-scan-period-ms\s*=\s*<(\d+)>", text).group(1))
            idle = int(re.search(r"poll-period-ms\s*=\s*<(\d+)>", text).group(1))
            with self.subTest(path.name):
                self.assertGreater(active, scan_ms)
                self.assertGreaterEqual(idle, active)

    def test_scanner_owns_every_declared_expander(self):
        for path in (LEFT_DTS, RIGHT_DTS):
            text = read(path)
            expanders = re.search(r"expanders\s*=\s*(.*?);", text, re.S)
            self.assertIsNotNone(expanders, path.name)
            declared = set(re.findall(r"&(\w+)", expanders.group(1)))
            used = {label for label, _ in key_inputs(path)}
            with self.subTest(path.name):
                self.assertEqual(declared, set(spec.EXPANDER_ADDRESSES))
                self.assertTrue(used <= declared)


class RoleTest(unittest.TestCase):
    def test_left_is_central_and_right_is_not(self):
        text = (BOARD / "Kconfig.defconfig").read_text()
        left = re.search(r"if BOARD_NOCFREE_AND_LEFT\n(.*?)\nendif", text, re.S).group(1)
        right = re.search(r"if BOARD_NOCFREE_AND_RIGHT\n(.*?)\nendif", text, re.S).group(1)
        self.assertIn("ZMK_SPLIT_ROLE_CENTRAL", left)
        self.assertNotIn("ZMK_SPLIT_ROLE_CENTRAL", right)
        self.assertIn("config ZMK_SPLIT\n    default y", text)

    def test_the_defconfigs_never_set_a_split_role(self):
        """Roles live in Kconfig.defconfig only. A defconfig override here
        would silently make both halves centrals and kill the right half."""
        for name in (
            "nocfree_and_left_nrf52833_zmk_defconfig",
            "nocfree_and_right_nrf52833_zmk_defconfig",
        ):
            with self.subTest(name):
                self.assertNotIn("ZMK_SPLIT_ROLE_CENTRAL", (BOARD / name).read_text())

    def test_only_the_central_presents_usb_hid(self):
        left = (BOARD / "nocfree_and_left_nrf52833_zmk_defconfig").read_text()
        right = (BOARD / "nocfree_and_right_nrf52833_zmk_defconfig").read_text()
        self.assertIn("CONFIG_ZMK_USB=y", left)
        self.assertNotIn("CONFIG_ZMK_USB=y", right)

    def test_both_halves_advertise_bluetooth(self):
        for name in (
            "nocfree_and_left_nrf52833_zmk_defconfig",
            "nocfree_and_right_nrf52833_zmk_defconfig",
        ):
            with self.subTest(name):
                self.assertIn("CONFIG_ZMK_BLE=y", (BOARD / name).read_text())

    def test_both_halves_keep_a_usb_recovery_interface(self):
        for name in (
            "nocfree_and_left_nrf52833_zmk_defconfig",
            "nocfree_and_right_nrf52833_zmk_defconfig",
        ):
            text = (BOARD / name).read_text()
            with self.subTest(name):
                self.assertIn("CONFIG_USB_CDC_ACM=y", text)
                self.assertIn("CONFIG_CDC_ACM_DTE_RATE_CALLBACK_SUPPORT=y", text)
                self.assertIn("CONFIG_RETENTION_BOOT_MODE=y", text)

    def test_the_peripheral_enumerates_usb_without_zmk_usb(self):
        """With CONFIG_ZMK_USB unset, ZMK never calls usb_enable(); these two
        lines are the only thing that brings up the right half's recovery
        interface. Losing either strands the peripheral without a
        connection-independent DFU path."""
        right = (BOARD / "nocfree_and_right_nrf52833_zmk_defconfig").read_text()
        self.assertIn("CONFIG_USB_DEVICE_STACK=y", right)
        self.assertIn("CONFIG_USB_DEVICE_INITIALIZE_AT_BOOT=y", right)

    def test_split_link_is_tuned_for_link_margin(self):
        """The split link favours reliability over throughput: ZMK's
        EXPERIMENTAL_CONN keeps every link on the more sensitive 1M PHY (at
        the pinned revision its only effect is disabling the controller's
        2M PHY), and a deeper BLE TX pipeline plus deeper state queues cover
        the known upstream gap where the split peripheral drops a key-state
        notification the stack refuses to accept. Both halves must set the
        link options or the PHY can still be negotiated up."""
        left = (BOARD / "nocfree_and_left_nrf52833_zmk_defconfig").read_text()
        right = (BOARD / "nocfree_and_right_nrf52833_zmk_defconfig").read_text()
        for name, text in (("left", left), ("right", right)):
            with self.subTest(name):
                self.assertIn("CONFIG_ZMK_BLE_EXPERIMENTAL_CONN=y", text)
                self.assertIn("CONFIG_BT_BUF_ACL_TX_COUNT=8", text)
                self.assertIn("CONFIG_BT_L2CAP_TX_BUF_COUNT=8", text)
                self.assertIn("CONFIG_BT_CONN_TX_MAX=8", text)
        self.assertIn("CONFIG_ZMK_SPLIT_BLE_CENTRAL_POSITION_QUEUE_SIZE=16", left)
        self.assertIn("CONFIG_ZMK_SPLIT_BLE_PERIPHERAL_POSITION_QUEUE_SIZE=32", right)

    def test_low_frequency_clock_stays_on_the_internal_rc(self):
        """No 32.768 kHz crystal is confirmed fitted. Selecting an absent
        crystal silently stops the BLE controller on both halves."""
        for name in (
            "nocfree_and_left_nrf52833_zmk_defconfig",
            "nocfree_and_right_nrf52833_zmk_defconfig",
        ):
            text = (BOARD / name).read_text()
            with self.subTest(name):
                self.assertIn("CONFIG_CLOCK_CONTROL_NRF_K32SRC_RC=y", text)
                self.assertNotIn("K32SRC_XTAL", text)

    def test_backlight_drives_only_the_factory_pin(self):
        """The backlight is the one output this port drives, on the published
        pin: P0.20, one PWM channel, non-inverted -- the drive is active high,
        established on hardware. See docs/backlight.md."""
        pinctrl = read(BOARD / "nocfree_and-pinctrl.dtsi")
        self.assertIn("NRF_PSEL(PWM_OUT0, 0, 20)", pinctrl)

        dtsi = read(BOARD / "nocfree_and.dtsi")
        self.assertIn("zmk,backlight = &backlight;", dtsi)
        # The period is a tuning knob with its own test below; pin the
        # channel and the polarity here, not the number.
        self.assertRegex(dtsi, r"pwms = <&pwm0 0 PWM_\w+\(\d+\) PWM_POLARITY_NORMAL>;")
        # One channel only: the factory driver disconnects PSEL.OUT[1..3].
        self.assertEqual(dtsi.count("pwms = <"), 1)

        for name in BOARD.glob("*_defconfig"):
            config = name.read_text()
            with self.subTest(name.name):
                self.assertIn("CONFIG_ZMK_BACKLIGHT=y", config)
                # Never bright at boot: an unverified polarity must not be
                # able to sit at full duty on battery.
                self.assertIn("CONFIG_ZMK_BACKLIGHT_ON_START=n", config)

    def test_the_backlight_pwm_stays_slow_enough_to_dim(self):
        """Raising the PWM rate raises the brightness floor on this hardware.

        25 kHz was tried once, to silence a whine the left half developed at
        1 % duty. It silenced it and cost the dimming: the duty ratio was the
        same either way, so the extra light is the LED stage's turn-off tail,
        which is a large share of a 40 us cycle and negligible in a 1 ms one.
        Keep the period slow and fight whine with a longer duty instead.
        """
        dtsi = read(BOARD / "nocfree_and.dtsi")
        period = re.search(r"pwms = <&pwm0 0 PWM_(MSEC|USEC|NSEC)\((\d+)\)", dtsi)
        self.assertIsNotNone(period, "backlight PWM period not found")

        scale = {"MSEC": 1_000_000, "USEC": 1_000, "NSEC": 1}
        period_ns = int(period.group(2)) * scale[period.group(1)]
        self.assertGreaterEqual(period_ns, 500_000, "too fast to reach a low brightness")

        # Below the flicker fusion threshold the backlight would strobe.
        self.assertLessEqual(period_ns, 20_000_000, "50 Hz or faster, else it flickers")

    def test_the_backlight_on_level_tunes_in_single_percent_steps(self):
        """BL_SET 100 makes each half's scale-percent its duty cycle directly.

        Brightness crosses the LED API as an integer 0..100, so a lower BL_SET
        would quantise the scale: at BL_SET 60 the reachable left-hand duties
        were 1, 2, 3, 5 ... with several scale values collapsing onto each. At
        100 the scale is the duty, and the halves still land on one number
        because the behaviour is global.
        """
        keymap = read(BOARD / "nocfree_and.keymap")
        self.assertIn("&bl BL_SET 100", keymap)

    def test_neither_half_is_scaled_past_the_duty_ceiling(self):
        """scale-percent above 100 is a no-op, not extra brightness.

        With BL_SET 100 the scale is the duty in percent, and duty saturates at
        100. A larger figure clamps and produces a bit-identical image, so a
        build that "turns the right half up" past the ceiling would look like a
        change and be none. Each half can only ever be taken down from here.
        """
        for half in ("left", "right"):
            dts = read(BOARD / f"nocfree_and_{half}_nrf52833_zmk.dts")
            found = re.search(r"scale-percent = <(\d+)>", dts)
            self.assertIsNotNone(found, f"{half} half declares no scale-percent")
            value = int(found.group(1))
            with self.subTest(half):
                self.assertGreater(value, 0, "a zero scale switches the half off")
                self.assertLessEqual(value, 100, "above the duty ceiling, so a no-op")

    def test_unverified_hardware_stays_disabled(self):
        """No other output pin, regulator mode or radio power is asserted."""
        text = " ".join(read(p) for p in BOARD.glob("*.dts*"))
        for forbidden in (
            "zmk,underglow",
            "gpio-leds",
            "regulator-initial-mode",
            # No devicetree mechanism may drive a pin either.
            "gpio-hog",
            "output-high",
            "output-low",
        ):
            with self.subTest(forbidden):
                self.assertNotIn(forbidden, text)

        for name in BOARD.glob("*_defconfig"):
            config = name.read_text()
            for forbidden in (
                "CONFIG_ZMK_RGB_UNDERGLOW",
                "CONFIG_BT_CTLR_TX_PWR",
            ):
                with self.subTest(f"{name.name} {forbidden}"):
                    self.assertNotIn(forbidden, config)

            # Battery reporting defaults on, so every half has to make a
            # deliberate choice. The left half measures (see below); the right
            # half must still say n, or it advertises a Battery Service with
            # nothing behind it.
            with self.subTest(f"{name.name} battery"):
                if "right" in name.name:
                    self.assertIn("CONFIG_ZMK_BATTERY_REPORTING=n", config)
                else:
                    self.assertIn("CONFIG_ZMK_BATTERY_REPORTING=y", config)

    def test_only_the_left_half_measures_the_battery(self):
        """The divider node is per-half: the enable pin differs between them.

        Section 4 of the porting guide puts the ADC on P0.04 (AIN2) on both
        halves but the divider enable on P0.05 left and P0.31 right, so a node
        shared through the .dtsi would drive the wrong pin on one of them.

        io-channels carries the bare AIN number because
        battery_voltage_divider.c computes `AnalogInput0 + channel` itself.
        """
        left = read(BOARD / "nocfree_and_left_nrf52833_zmk.dts")
        right = read(BOARD / "nocfree_and_right_nrf52833_zmk.dts")

        self.assertIn("zmk,battery-voltage-divider", left)
        self.assertIn("io-channels = <&adc 2>", left)
        self.assertIn("power-gpios = <&gpio0 5 GPIO_ACTIVE_HIGH>", left)
        self.assertIn("zmk,battery = &vbatt", left)

        # Step 2 of the battery plan adds the right half; until then it must
        # not carry a divider node with the left half's enable pin.
        self.assertNotIn("zmk,battery-voltage-divider", right)

    def test_the_battery_readout_is_bound_where_the_factory_firmware_had_it(self):
        """Fn+i types the level, matching the factory firmware's muscle memory.

        The binding has to line up with the I key in the base layer: the two
        layers are position-indexed, so an off-by-one here would silently put
        the readout on a neighbouring key.
        """
        keymap = read(BOARD / "nocfree_and.keymap")
        self.assertIn("nocfree,behavior-battery-report", keymap)

        base = _layer_bindings(keymap, "default_layer")
        fn = _layer_bindings(keymap, "function_layer")
        self.assertEqual(len(base), len(fn))

        positions = [i for i, b in enumerate(fn) if b.startswith("&batt_report")]
        self.assertEqual(len(positions), 1, "expected exactly one battery readout binding")
        self.assertEqual(base[positions[0]], "&kp I")

    def test_the_battery_readout_only_types_layout_stable_characters(self):
        """Keycodes are positional and the owner types German ISO.

        Digits, letters and space sit in the same places on ANSI and ISO DE.
        Punctuation does not, so a '%' in the output would type as something
        else. The behaviour must not reach for one.
        """
        source = (ROOT / "src/behaviors/behavior_battery_report.c").read_text()
        for forbidden in ("PERCENT", "PRCNT", "LS(", "HID_USAGE_KEY_KEYBOARD_MINUS"):
            with self.subTest(forbidden):
                self.assertNotIn(forbidden, source)

    def test_the_battery_divider_declares_a_step_up_ratio(self):
        """The divider node is well-formed and scales upward.

        This deliberately does NOT pin the ratio. An earlier version asserted
        full-ohms = 150 as "measured on hardware"; it was not. That figure came
        from a single reading of a full battery on a cable, and with it the
        readout saturates at 100 % -- lithium_ion_mv_to_pct() clamps at 4200 mV,
        which a 1.5 ratio reaches at 2.80 V on the pin. See docs/battery.md.

        So all that is checked is what must hold for any candidate ratio: the
        properties exist and full-ohms exceeds output-ohms, because a battery
        divider steps down and the driver corrects for it. Whoever calibrates
        this properly should be free to change the number.
        """
        left = read(BOARD / "nocfree_and_left_nrf52833_zmk.dts")
        output = re.search(r"output-ohms = <(\d+)>", left)
        full = re.search(r"full-ohms = <(\d+)>", left)
        self.assertIsNotNone(output, "divider declares no output-ohms")
        self.assertIsNotNone(full, "divider declares no full-ohms")
        self.assertGreater(int(full.group(1)), int(output.group(1)))


class MetadataTest(unittest.TestCase):
    def test_module_name_follows_the_zmk_convention(self):
        text = (ROOT / "zephyr/module.yml").read_text()
        self.assertIn("name: zmk-keyboard-nocfree-and", text)
        self.assertIn("board_root: .", text)
        self.assertIn("dts_root: .", text)

    def test_board_yml_declares_both_halves_with_the_zmk_variant(self):
        text = (BOARD / "board.yml").read_text()
        for name in ("nocfree_and_left", "nocfree_and_right"):
            self.assertIn(f"name: {name}", text)
        self.assertEqual(text.count("name: nrf52833"), 2)
        self.assertEqual(text.count("name: zmk"), 2)

    def test_hardware_metadata_has_the_required_fields(self):
        text = (BOARD / "nocfree_and.zmk.yml").read_text()
        for required in ('file_format: "1"', "id: nocfree_and", "type: board", "arch: arm"):
            with self.subTest(required):
                self.assertIn(required, text)
        self.assertIn("nocfree_and_left//zmk", text)
        self.assertIn("nocfree_and_right//zmk", text)
        self.assertIn("- keys", text)

    def test_build_matrix_covers_both_roles(self):
        text = (ROOT / "build.yaml").read_text()
        self.assertIn("nocfree_and_left/nrf52833/zmk", text)
        self.assertIn("nocfree_and_right/nrf52833/zmk", text)

    def test_dependencies_are_public_and_pinned(self):
        text = (ROOT / "config/west.yml").read_text()
        self.assertIn("url-base: https://github.com/zmkfirmware", text)
        revision = re.search(r"revision:\s*([0-9a-f]{40})", text)
        self.assertIsNotNone(revision, "ZMK must be pinned to an exact commit")


if __name__ == "__main__":
    unittest.main()
