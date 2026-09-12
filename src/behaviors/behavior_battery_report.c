/*
 * Copyright (c) 2026 The NocFree ZMK Contributors
 *
 * SPDX-License-Identifier: MIT
 */

/*
 * Types the battery level out as keystrokes.
 *
 * This exists because the owner runs the keyboard wired, and USB HID has no
 * battery channel: a level published as a BLE service is measured but
 * invisible to them. The factory firmware solved it the same way, on Fn+i,
 * which is where this is bound to match the muscle memory already there.
 *
 * A ZMK macro cannot do this. Macros send a fixed sequence fixed at compile
 * time, and the percentage is a runtime integer, so the digits have to be
 * converted to keycodes and queued here.
 *
 * German ISO: keycodes are positional, so anything whose position differs
 * between layouts would type as some other character. Digits, letters and
 * space are identical on ANSI and ISO DE, so the output is restricted to
 * those -- no '%' and no punctuation. See docs/battery.md.
 */

#define DT_DRV_COMPAT nocfree_behavior_battery_report

#include <zephyr/device.h>
#include <drivers/behavior.h>
#include <zephyr/logging/log.h>

#include <dt-bindings/zmk/hid_usage.h>
#include <dt-bindings/zmk/hid_usage_pages.h>
#include <zmk/battery.h>
#include <zmk/behavior.h>
#include <zmk/behavior_queue.h>
#include <zmk/hid.h>

LOG_MODULE_DECLARE(zmk, CONFIG_ZMK_LOG_LEVEL);

#if DT_HAS_COMPAT_STATUS_OKAY(DT_DRV_COMPAT)

/*
 * Wait between the queued taps. ZMK's macro default is 15 ms; the same value
 * is used here so the output behaves like every other queued sequence.
 */
#define TAP_MS 15

struct battery_report_config {
    uint8_t tap_ms;
};

/* HID usages for the characters this behaviour can type. */
#define USAGE_1 HID_USAGE_KEY_KEYBOARD_1_AND_EXCLAMATION       /* 0x1E */
#define USAGE_0 HID_USAGE_KEY_KEYBOARD_0_AND_RIGHT_PARENTHESIS /* 0x27 */
#define USAGE_A HID_USAGE_KEY_KEYBOARD_A                       /* 0x04 */
#define USAGE_SPACE HID_USAGE_KEY_KEYBOARD_SPACEBAR            /* 0x2C */

static uint32_t encode(uint16_t usage) {
    return ZMK_HID_USAGE(HID_USAGE_KEY, usage);
}

/*
 * '1'..'9' run 0x1E..0x26 but '0' sits above them at 0x27, so it cannot be
 * reached by adding an offset and needs its own case.
 */
static uint32_t digit_usage(uint8_t digit) {
    return digit == 0 ? encode(USAGE_0) : encode(USAGE_1 + digit - 1);
}

static uint32_t letter_usage(char lower) { return encode(USAGE_A + (lower - 'a')); }

static int queue_tap(const struct zmk_behavior_binding_event *event, uint32_t keycode,
                     uint8_t tap_ms) {
    struct zmk_behavior_binding binding = {
        .behavior_dev = "key_press",
        .param1 = keycode,
    };

    int err = zmk_behavior_queue_add(event, binding, true, tap_ms);
    if (err < 0) {
        return err;
    }

    return zmk_behavior_queue_add(event, binding, false, tap_ms);
}

static int on_keymap_binding_pressed(struct zmk_behavior_binding *binding,
                                     struct zmk_behavior_binding_event event) {
    const struct device *dev = zmk_behavior_get_binding(binding->behavior_dev);
    const struct battery_report_config *cfg = dev->config;

    uint8_t soc = zmk_battery_state_of_charge();

    LOG_DBG("battery %d%%", soc);

    /*
     * "bat NNN" -- at most 7 characters, 14 queue entries, well inside the
     * 64-entry default. The label makes the number self-explanatory when it
     * appears in the middle of whatever was being typed; "%" is deliberately
     * absent because it is not layout-stable.
     */
    int err = queue_tap(&event, letter_usage('b'), cfg->tap_ms);
    if (err < 0) {
        goto full;
    }
    if ((err = queue_tap(&event, letter_usage('a'), cfg->tap_ms)) < 0) {
        goto full;
    }
    if ((err = queue_tap(&event, letter_usage('t'), cfg->tap_ms)) < 0) {
        goto full;
    }
    if ((err = queue_tap(&event, encode(USAGE_SPACE), cfg->tap_ms)) < 0) {
        goto full;
    }

    /* Leading digits only when present, so 7 types as "bat 7", not "bat 007". */
    if (soc >= 100) {
        if ((err = queue_tap(&event, digit_usage(soc / 100), cfg->tap_ms)) < 0) {
            goto full;
        }
    }
    if (soc >= 10) {
        if ((err = queue_tap(&event, digit_usage((soc / 10) % 10), cfg->tap_ms)) < 0) {
            goto full;
        }
    }
    if ((err = queue_tap(&event, digit_usage(soc % 10), cfg->tap_ms)) < 0) {
        goto full;
    }

    return ZMK_BEHAVIOR_OPAQUE;

full:
    /*
     * The queue is shared with macros and hold-taps. If it is full the line is
     * truncated rather than retried: this is a status readout, and blocking or
     * dropping real keystrokes to finish it would be the worse failure.
     */
    LOG_WRN("Behavior queue full, battery line truncated (%d)", err);
    return ZMK_BEHAVIOR_OPAQUE;
}

static int on_keymap_binding_released(struct zmk_behavior_binding *binding,
                                      struct zmk_behavior_binding_event event) {
    return ZMK_BEHAVIOR_OPAQUE;
}

static const struct behavior_driver_api behavior_battery_report_driver_api = {
    .binding_pressed = on_keymap_binding_pressed,
    .binding_released = on_keymap_binding_released,
#if IS_ENABLED(CONFIG_ZMK_BEHAVIOR_METADATA)
    .get_parameter_metadata = zmk_behavior_get_empty_param_metadata,
#endif // IS_ENABLED(CONFIG_ZMK_BEHAVIOR_METADATA)
};

#define BR_INST(n)                                                                                 \
    static const struct battery_report_config battery_report_config_##n = {                        \
        .tap_ms = DT_INST_PROP_OR(n, tap_ms, TAP_MS),                                              \
    };                                                                                             \
    BEHAVIOR_DT_INST_DEFINE(n, NULL, NULL, NULL, &battery_report_config_##n, POST_KERNEL,          \
                            CONFIG_KERNEL_INIT_PRIORITY_DEFAULT,                                   \
                            &behavior_battery_report_driver_api);

DT_INST_FOREACH_STATUS_OKAY(BR_INST)

#endif /* DT_HAS_COMPAT_STATUS_OKAY(DT_DRV_COMPAT) */
