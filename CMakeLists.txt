# SPDX-License-Identifier: MIT

if(CONFIG_NOCFREE_KSCAN_PCA9555 OR CONFIG_NOCFREE_RECOVERY_CDC_1200_TOUCH
   OR CONFIG_NOCFREE_SCALED_LED OR CONFIG_NOCFREE_BEHAVIOR_BATTERY_REPORT)
  zephyr_library()
  zephyr_library_sources_ifdef(CONFIG_NOCFREE_KSCAN_PCA9555 drivers/kscan/kscan_pca9555.c)
  zephyr_library_sources_ifdef(CONFIG_NOCFREE_SCALED_LED drivers/led/scaled_led.c)
  zephyr_library_sources_ifdef(CONFIG_NOCFREE_RECOVERY_CDC_1200_TOUCH src/cdc_1200_touch.c)
  zephyr_library_sources_ifdef(CONFIG_NOCFREE_BEHAVIOR_BATTERY_REPORT
                               src/behaviors/behavior_battery_report.c)

  # Behaviour headers (drivers/behavior.h, zmk/behavior_queue.h) live in ZMK's
  # application include directory. ZMK adds that directory to its own app
  # target as PRIVATE, so modules never inherit it -- a module only sees
  # app/module/include. Anything implementing a behaviour has to add it back.
  #
  # ZMK is the Zephyr application here, so APPLICATION_SOURCE_DIR is zmk/app.
  if(CONFIG_NOCFREE_BEHAVIOR_BATTERY_REPORT)
    zephyr_library_include_directories(${APPLICATION_SOURCE_DIR}/include)
  endif()
endif()
