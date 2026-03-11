obj-m += tuxedo_nb04_rgb_perkey.o

KDIR := /lib/modules/$(shell uname -r)/build
PWD := $(shell pwd)

# Use the same compiler as the kernel when available (NVIDIA approach)
ifeq ($(origin CC),default)
    cc_version_text := $(firstword $(shell . $(KDIR)/.config 2>/dev/null; echo "$$CONFIG_CC_VERSION_TEXT"))
    ifneq ($(cc_version_text),)
        ifeq ($(shell command -v $(cc_version_text) 2>/dev/null),)
            $(warning Unable to locate compiler $(cc_version_text) from kernel config; using default)
        else
            CC := $(cc_version_text)
        endif
    endif
endif

CC ?= cc

all:
	$(MAKE) CC=$(CC) -C $(KDIR) M=$(PWD) modules

clean:
	$(MAKE) CC=$(CC) -C $(KDIR) M=$(PWD) clean
	rm -f *.o *.ko *.mod.c *.mod *.order *.symvers

install:
	sudo insmod tuxedo_nb04_rgb_perkey.ko
	@echo ""
	@echo "Module loaded! Check dmesg:"
	@dmesg | tail -10

uninstall:
	sudo rmmod tuxedo_nb04_rgb_perkey || true

reload:
	$(MAKE) uninstall || true
	$(MAKE) clean
	$(MAKE) all
	$(MAKE) install

help:
	@echo "TUXEDO Keyboard RGB - Kernel Module"
	@echo ""
	@echo "Available targets:"
	@echo "  make all        - Build the kernel module"
	@echo "  make clean      - Clean build artifacts"
	@echo "  make install    - Load the kernel module"
	@echo "  make uninstall  - Unload the kernel module"
	@echo "  make reload     - Rebuild and reload the module"
	@echo ""
	@echo "Sysfs interface: /sys/kernel/tuxedo_nb04_rgb_perkey/"
	@echo "  - /sys/kernel/tuxedo_nb04_rgb_perkey/batch - RGB data batch interface"
	@echo ""
	@echo "Use the GUI to control keyboard colors:"
	@echo "  ./run_gui.sh"

.PHONY: all clean install uninstall reload help
