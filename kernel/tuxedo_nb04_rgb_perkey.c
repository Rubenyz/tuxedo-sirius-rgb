// SPDX-License-Identifier: GPL-2.0
/*
 * TUXEDO NB04 Per-Key RGB Keyboard Driver
 *
 * Copyright (c) 2023 TUXEDO Computers GmbH <tux@tuxedocomputers.com>
 *   - WMI interface data structures (union tux_wmi_xx_496in_80out_*,
 *     TUX_KBL_SET_MULTIPLE_KEYS_LIGHTING_SETTINGS_COUNT_MAX) derived from
 *     drivers/platform/x86/tuxedo/tuxedo_nb04_wmi_ab.c
 *
 * Copyright (c) 2026 Ruben <ruben@rbsworks.nl>
 *   - Per-key RGB sysfs interface (batch, cmd, lightbar)
 *   - WMI probe/init/exit logic
 */

#include <linux/module.h>
#include <linux/kernel.h>
#include <linux/wmi.h>
#include <linux/kobject.h>
#include <linux/sysfs.h>
#include <linux/string.h>

// From wmi_util.h
#define TUX_KBL_SET_MULTIPLE_KEYS_LIGHTING_SETTINGS_COUNT_MAX	120

union tux_wmi_xx_496in_80out_in_t {
	u8 raw[496];
	struct __packed {
		u8 reserved[15];
		u8 rgb_configs_cnt;
		struct {
			u8 key_id;
			u8 red;
			u8 green;
			u8 blue;
		} rgb_configs[TUX_KBL_SET_MULTIPLE_KEYS_LIGHTING_SETTINGS_COUNT_MAX];
	} kbl_set_multiple_keys_in;
};

union tux_wmi_xx_496in_80out_out_t {
	u8 raw[80];
	struct __packed {
		u8 return_value;
		u8 reserved[79];
	} kbl_set_multiple_keys_out;
};

enum tux_wmi_xx_496in_80out_methods {
	TUX_KBL_SET_MULTIPLE_KEYS = 6,
};

enum tux_wmi_normal_methods {
	TUX_KBL_SET_ZONE = 3,
};

// From wmi_util.c
static int tux_wmi_xx_496in_80out(struct wmi_device *wdev,
				  enum tux_wmi_xx_496in_80out_methods method,
				  union tux_wmi_xx_496in_80out_in_t *in,
				  union tux_wmi_xx_496in_80out_out_t *out)
{
	struct acpi_buffer acpi_buffer_in = { 496, in->raw };
	struct acpi_buffer acpi_buffer_out = { ACPI_ALLOCATE_BUFFER, NULL };
	union acpi_object *acpi_object_out = NULL;
	acpi_status status;
	int ret = 0;

	dev_info(&wdev->dev, "Calling Method %u with 496 bytes input\n", method);
	print_hex_dump_bytes("Input: ", DUMP_PREFIX_OFFSET, in->raw, 32);

	status = wmidev_evaluate_method(wdev, 0, method, &acpi_buffer_in, &acpi_buffer_out);
	
	if (ACPI_FAILURE(status)) {
		dev_err(&wdev->dev, "WMI call failed: 0x%x\n", status);
		return -EIO;
	}
	
	acpi_object_out = acpi_buffer_out.pointer;
	if (!acpi_object_out) {
		dev_err(&wdev->dev, "No output from WMI\n");
		return -ENODATA;
	}

	if (acpi_object_out->type != ACPI_TYPE_BUFFER) {
		dev_err(&wdev->dev, "Unexpected output type: %u\n", acpi_object_out->type);
		kfree(acpi_object_out);
		return -EIO;
	}
	
	if (acpi_object_out->buffer.length < 80) {
		dev_err(&wdev->dev, "Output buffer too short: %u\n", acpi_object_out->buffer.length);
		kfree(acpi_object_out);
		return -EIO;
	}

	memcpy(out->raw, acpi_object_out->buffer.pointer, 80);
	
	dev_info(&wdev->dev, "✓ WMI call succeeded! Return value: 0x%02x\n", out->kbl_set_multiple_keys_out.return_value);
	print_hex_dump_bytes("Output: ", DUMP_PREFIX_OFFSET, out->raw, 16);
	
	kfree(acpi_object_out);
	return ret;
}

static int call_method_normal(struct wmi_device *wdev, u32 method, u8 *buf, int len)
{
	struct acpi_buffer acpi_buffer_in = { len, buf };
	struct acpi_buffer acpi_buffer_out = { ACPI_ALLOCATE_BUFFER, NULL };
	acpi_status status;

	status = wmidev_evaluate_method(wdev, 0, method, &acpi_buffer_in, &acpi_buffer_out);
	kfree(acpi_buffer_out.pointer);

	if (ACPI_FAILURE(status)) {
		dev_err(&wdev->dev, "WMI method %u failed: 0x%x\n", method, status);
		return -EIO;
	}
	return 0;
}

// Global WMI device
static struct wmi_device *g_wdev = NULL;
static struct kobject *test_kobj = NULL;

static int set_multiple_keys(u8 *key_ids, u8 *reds, u8 *greens, u8 *blues, int count)
{
	union tux_wmi_xx_496in_80out_in_t in;
	union tux_wmi_xx_496in_80out_out_t out;
	int i, ret;
	
	if (count > TUX_KBL_SET_MULTIPLE_KEYS_LIGHTING_SETTINGS_COUNT_MAX) {
		pr_err("tuxedo_nb04_rgb_perkey: Too many keys! Max is %d\n", TUX_KBL_SET_MULTIPLE_KEYS_LIGHTING_SETTINGS_COUNT_MAX);
		return -EINVAL;
	}
	
	memset(&in, 0, sizeof(in));
	
	in.kbl_set_multiple_keys_in.rgb_configs_cnt = count;
	for (i = 0; i < count; i++) {
		in.kbl_set_multiple_keys_in.rgb_configs[i].key_id = key_ids[i];
		in.kbl_set_multiple_keys_in.rgb_configs[i].red = reds[i];
		in.kbl_set_multiple_keys_in.rgb_configs[i].green = greens[i];
		in.kbl_set_multiple_keys_in.rgb_configs[i].blue = blues[i];
	}
	
	ret = tux_wmi_xx_496in_80out(g_wdev, TUX_KBL_SET_MULTIPLE_KEYS, &in, &out);
	
	if (ret == 0) {
		pr_info("tuxedo_nb04_rgb_perkey: ✓ Set %d key(s)\n", count);
	} else {
		pr_err("tuxedo_nb04_rgb_perkey: FAILED with error %d\n", ret);
	}
	
	return ret;
}

static ssize_t cmd_store(struct kobject *kobj, struct kobj_attribute *attr,
                         const char *buf, size_t count)
{
	unsigned int key_id, r, g, b;
	int parsed;
	u8 single_key, single_r, single_g, single_b;
	
	if (!g_wdev) {
		pr_err("tuxedo_nb04_rgb_perkey: WMI device not found!\n");
		return -ENODEV;
	}
	
	// Parse: "KEY_ID R G B" format (e.g., "1A 255 0 0")
	parsed = sscanf(buf, "%x %u %u %u", &key_id, &r, &g, &b);
	if (parsed == 4) {
		// Validate ranges
		if (key_id > 0xFF || r > 255 || g > 255 || b > 255) {
			pr_err("tuxedo_nb04_rgb_perkey: Invalid values! KEY_ID must be 0x00-0xFF, RGB must be 0-255\n");
			return -EINVAL;
		}
		
		single_key = (u8)key_id;
		single_r = (u8)r;
		single_g = (u8)g;
		single_b = (u8)b;
		
		pr_info("tuxedo_nb04_rgb_perkey: Setting key 0x%02x to RGB(%d,%d,%d)\n", single_key, single_r, single_g, single_b);
		set_multiple_keys(&single_key, &single_r, &single_g, &single_b, 1);
		return count;
	}
	
	pr_info("tuxedo_nb04_rgb_perkey: Usage:\n");
	pr_info("  Single key: echo '<KEY_ID(hex)> <R> <G> <B>' > /sys/kernel/tuxedo_nb04_rgb_perkey/cmd\n");
	pr_info("  Example: echo '1A 255 0 0' > /sys/kernel/tuxedo_nb04_rgb_perkey/cmd  # W=RED\n");
	
	return count;
}

static ssize_t batch_store(struct kobject *kobj, struct kobj_attribute *attr,
                           const char *buf, size_t count)
{
	u8 key_ids[TUX_KBL_SET_MULTIPLE_KEYS_LIGHTING_SETTINGS_COUNT_MAX];
	u8 reds[TUX_KBL_SET_MULTIPLE_KEYS_LIGHTING_SETTINGS_COUNT_MAX];
	u8 greens[TUX_KBL_SET_MULTIPLE_KEYS_LIGHTING_SETTINGS_COUNT_MAX];
	u8 blues[TUX_KBL_SET_MULTIPLE_KEYS_LIGHTING_SETTINGS_COUNT_MAX];
	int num_keys, i;
	
	if (!g_wdev) {
		pr_err("tuxedo_nb04_rgb_perkey: WMI device not found!\n");
		return -ENODEV;
	}
	
	// Data format: KEY_ID R G B KEY_ID R G B ... (4 bytes per key)
	if (count % 4 != 0) {
		pr_err("tuxedo_nb04_rgb_perkey: Invalid batch size! Must be multiple of 4 (got %zu)\n", count);
		return -EINVAL;
	}
	
	num_keys = count / 4;
	
	if (num_keys > TUX_KBL_SET_MULTIPLE_KEYS_LIGHTING_SETTINGS_COUNT_MAX) {
		pr_err("tuxedo_nb04_rgb_perkey: Too many keys in batch! Max %d, got %d\n", 
		       TUX_KBL_SET_MULTIPLE_KEYS_LIGHTING_SETTINGS_COUNT_MAX, num_keys);
		return -EINVAL;
	}
	
	if (num_keys == 0) {
		pr_warn("tuxedo_nb04_rgb_perkey: Empty batch, nothing to do\n");
		return count;
	}
	
	// Parse the batch data
	for (i = 0; i < num_keys; i++) {
		key_ids[i] = (u8)buf[i * 4 + 0];
		reds[i]    = (u8)buf[i * 4 + 1];
		greens[i]  = (u8)buf[i * 4 + 2];
		blues[i]   = (u8)buf[i * 4 + 3];
	}
	
	pr_info("tuxedo_nb04_rgb_perkey: Batch update: %d keys\n", num_keys);
	set_multiple_keys(key_ids, reds, greens, blues, num_keys);
	
	return count;
}

static struct kobj_attribute cmd_attribute = __ATTR(cmd, 0220, NULL, cmd_store);
static struct kobj_attribute batch_attribute = __ATTR(batch, 0220, NULL, batch_store);

static ssize_t lightbar_store(struct kobject *kobj, struct kobj_attribute *attr,
                              const char *buf, size_t count)
{
	unsigned int zone, r, g, b, brightness, enable;
	u8 data[8];
	int ret;
	
	if (!g_wdev) {
		pr_err("tuxedo_nb04_rgb_perkey: WMI device not found!\n");
		return -ENODEV;
	}
	
	// Parse: "ZONE R G B BRIGHTNESS ENABLE" format (e.g., "16 255 0 0 10 1")
	// ZONE: 0x10 (left), 0x20 (right), 0x30 (both)
	if (sscanf(buf, "%u %u %u %u %u %u", &zone, &r, &g, &b, &brightness, &enable) != 6) {
		pr_err("tuxedo_nb04_rgb_perkey: Usage: echo '<ZONE> <R> <G> <B> <BRIGHTNESS> <ENABLE>' > /sys/kernel/tuxedo_nb04_rgb_perkey/lightbar\n");
		return -EINVAL;
	}
	
	if (zone > 0xFF || r > 255 || g > 255 || b > 255 || brightness > 255 || enable > 1) {
		pr_err("tuxedo_nb04_rgb_perkey: Invalid values! ZONE/RGB/BRIGHTNESS must be 0-255, ENABLE must be 0-1\n");
		return -EINVAL;
	}
	
	data[0] = (u8)zone;
	data[1] = (u8)r;
	data[2] = (u8)g;
	data[3] = (u8)b;
	data[4] = (u8)brightness;
	data[5] = 0xFE; // mode byte (constant per WMI spec)
	data[6] = 0x00; // reserved
	data[7] = (u8)enable;
	
	pr_info("tuxedo_nb04_rgb_perkey: Setting lightbar zone 0x%02x to RGB(%d,%d,%d) brightness=%d enable=%d\n",
	        zone, r, g, b, brightness, enable);
	
	ret = call_method_normal(g_wdev, TUX_KBL_SET_ZONE, data, 8);
	if (ret) {
		pr_err("tuxedo_nb04_rgb_perkey: Lightbar WMI call FAILED with error %d\n", ret);
		return ret;
	}
	
	return count;
}

static struct kobj_attribute lightbar_attribute = __ATTR(lightbar, 0220, NULL, lightbar_store);

static int tuxedo_nb04_rgb_perkey_probe(struct wmi_device *wdev, const void *context)
{
	pr_info("tuxedo_nb04_rgb_perkey: WMI device probed!\n");
	g_wdev = wdev;
	return 0;
}

static void tuxedo_nb04_rgb_perkey_remove(struct wmi_device *wdev)
{
	pr_info("tuxedo_nb04_rgb_perkey: WMI device removed\n");
	g_wdev = NULL;
}

static const struct wmi_device_id tuxedo_nb04_rgb_perkey_id_table[] = {
	{ .guid_string = "80C9BAA6-AC48-4538-9234-9F81A55E7C85" },
	{ }
};

static struct wmi_driver tuxedo_nb04_rgb_perkey_driver = {
	.driver = {
		.name = "tuxedo_nb04_rgb_perkey",
	},
	.id_table = tuxedo_nb04_rgb_perkey_id_table,
	.probe = tuxedo_nb04_rgb_perkey_probe,
	.remove = tuxedo_nb04_rgb_perkey_remove,
};

static int __init tuxedo_nb04_rgb_perkey_init(void)
{
	int ret;
	
	pr_info("tuxedo_nb04_rgb_perkey: Loading...\n");
	
	test_kobj = kobject_create_and_add("tuxedo_nb04_rgb_perkey", kernel_kobj);
	if (!test_kobj)
		return -ENOMEM;
	
	ret = sysfs_create_file(test_kobj, &cmd_attribute.attr);
	if (ret) {
		kobject_put(test_kobj);
		return ret;
	}
	
	ret = sysfs_create_file(test_kobj, &batch_attribute.attr);
	if (ret) {
		sysfs_remove_file(test_kobj, &cmd_attribute.attr);
		kobject_put(test_kobj);
		return ret;
	}
	
	ret = sysfs_create_file(test_kobj, &lightbar_attribute.attr);
	if (ret) {
		sysfs_remove_file(test_kobj, &batch_attribute.attr);
		sysfs_remove_file(test_kobj, &cmd_attribute.attr);
		kobject_put(test_kobj);
		return ret;
	}
	
	ret = wmi_driver_register(&tuxedo_nb04_rgb_perkey_driver);
	if (ret) {
		sysfs_remove_file(test_kobj, &lightbar_attribute.attr);
		sysfs_remove_file(test_kobj, &batch_attribute.attr);
		sysfs_remove_file(test_kobj, &cmd_attribute.attr);
		kobject_put(test_kobj);
		return ret;
	}
	
	pr_info("tuxedo_nb04_rgb_perkey: Loaded! Interfaces:\n");
	pr_info("  /sys/kernel/tuxedo_nb04_rgb_perkey/cmd (text)\n");
	pr_info("  /sys/kernel/tuxedo_nb04_rgb_perkey/batch (binary)\n");
	pr_info("  /sys/kernel/tuxedo_nb04_rgb_perkey/lightbar (text)\n");
	return 0;
}

static void __exit tuxedo_nb04_rgb_perkey_exit(void)
{
	wmi_driver_unregister(&tuxedo_nb04_rgb_perkey_driver);
	sysfs_remove_file(test_kobj, &lightbar_attribute.attr);
	sysfs_remove_file(test_kobj, &batch_attribute.attr);
	sysfs_remove_file(test_kobj, &cmd_attribute.attr);
	kobject_put(test_kobj);
	pr_info("tuxedo_nb04_rgb_perkey: Unloaded\n");
}

module_init(tuxedo_nb04_rgb_perkey_init);
module_exit(tuxedo_nb04_rgb_perkey_exit);

MODULE_AUTHOR("Ruben");
MODULE_DESCRIPTION("TUXEDO NB04 Per-Key RGB Keyboard Driver");
MODULE_LICENSE("GPL");
MODULE_DEVICE_TABLE(wmi, tuxedo_nb04_rgb_perkey_id_table);
