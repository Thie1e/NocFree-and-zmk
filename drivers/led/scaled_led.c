/*
 * Copyright (c) 2026 The NocFree ZMK Contributors
 *
 * SPDX-License-Identifier: MIT
 */

/*
 * A LED device that applies a fixed scale and forwards to another LED device.
 *
 * ZMK sends one brightness value to every half of a split keyboard and has no
 * per-half adjustment. On this keyboard the halves do not reach the same
 * brightness at the same duty, so the correction is applied here, in the
 * device the keymap's backlight behaviour ends up talking to.
 *
 * The node must carry one child per LED of its target: ZMK derives its LED
 * count from DT_NUM_CHILD of the chosen backlight node, and iterates that many
 * indices through this device. That cannot be checked with BUILD_ASSERT here --
 * DT_NUM_CHILD of a phandle-derived node identifier does not survive macro
 * expansion inside one -- so it is a rule of the binding, not of the code.
 */

#define DT_DRV_COMPAT nocfree_scaled_led

#include <zephyr/device.h>
#include <zephyr/devicetree.h>
#include <zephyr/drivers/led.h>
#include <zephyr/logging/log.h>

LOG_MODULE_REGISTER(nocfree_scaled_led, CONFIG_LED_LOG_LEVEL);

#define BRIGHTNESS_MAX 100U

struct scaled_led_config {
    const struct device *target;
    uint16_t scale;
};

static uint8_t scale_brightness(const struct scaled_led_config *config, uint8_t value) {
    /*
     * Round to nearest, not down. Brightness is an integer percentage, so a
     * small scale truncates every reachable setting to zero -- a scale of 1
     * would turn the half off entirely instead of running it at its dimmest
     * step. Zero in still means zero out: 0 * scale rounds to 0.
     */
    uint32_t scaled = ((uint32_t)value * config->scale + 50U) / 100U;

    return (uint8_t)MIN(scaled, BRIGHTNESS_MAX);
}

static int scaled_led_set_brightness(const struct device *dev, uint32_t led, uint8_t value) {
    const struct scaled_led_config *config = dev->config;

    return led_set_brightness(config->target, led, scale_brightness(config, value));
}

static int scaled_led_on(const struct device *dev, uint32_t led) {
    return scaled_led_set_brightness(dev, led, BRIGHTNESS_MAX);
}

static int scaled_led_off(const struct device *dev, uint32_t led) {
    return scaled_led_set_brightness(dev, led, 0);
}

static int scaled_led_init(const struct device *dev) {
    const struct scaled_led_config *config = dev->config;

    if (!device_is_ready(config->target)) {
        LOG_ERR("Target LED device \"%s\" is not ready", config->target->name);
        return -ENODEV;
    }

    return 0;
}

static DEVICE_API(led, scaled_led_api) = {
    .on = scaled_led_on,
    .off = scaled_led_off,
    .set_brightness = scaled_led_set_brightness,
};

#define SCALED_LED_INIT(n)                                                                         \
    BUILD_ASSERT(DT_INST_PROP(n, scale_percent) > 0,                                               \
                 "scale-percent must be greater than zero");                                       \
    BUILD_ASSERT(DT_INST_PROP(n, scale_percent) <= 1000,                                           \
                 "scale-percent is implausibly large");                                            \
                                                                                                   \
    static const struct scaled_led_config scaled_led_config_##n = {                                \
        .target = DEVICE_DT_GET(DT_INST_PHANDLE(n, target)),                                       \
        .scale = DT_INST_PROP(n, scale_percent),                                                   \
    };                                                                                             \
                                                                                                   \
    DEVICE_DT_INST_DEFINE(n, scaled_led_init, NULL, NULL, &scaled_led_config_##n,                  \
                          POST_KERNEL, CONFIG_NOCFREE_SCALED_LED_INIT_PRIORITY,                    \
                          &scaled_led_api);

DT_INST_FOREACH_STATUS_OKAY(SCALED_LED_INIT)
