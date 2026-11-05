# ROCK 5T hub image

The board that is in use now boots the 32 GB Radxa Debian card, not this image. The product path is Docker Compose in [deploy/rock5t/compose.yaml](../deploy/rock5t/compose.yaml), documented in [ha-cutover.md](ha-cutover.md). This file describes the Buildroot image, which is kept and is not the boot disk.



The hub appliance image is a Buildroot rootfs on the Radxa ROCK 5T. It boots with the Radxa vendor loader and the Radxa 6.1 kernel, the same chain as the ROCK 5T Debian r7 image. The hub, its Python virtualenv, Node, and the radio data live on a separate `hub-data` partition so a rootfs rewrite can leave them in place.

The card that is running now is the original 128 GB SD. SSH is `root@10.0.0.85` (the cabled RTL8125B is `00:48:54:21:90:1c`). The root password in the image defconfig is `radxa`. The hub login is still `owner` / `changeme` until it is changed on the data partition.

## What is in the tree

| Path | Role |
|---|---|
| `os/buildroot/` | Buildroot external tree (`BR2_EXTERNAL`) |
| `os/buildroot/configs/home_ai_rock5t_defconfig` | Image config |
| `os/buildroot/board/rock5t/genimage.cfg` | GPT layout of `sdcard.img`, including the two rootfs slots |
| `os/buildroot/board/rock5t/boot.cmd` | U-Boot script that chooses a slot and counts boot attempts |
| `os/buildroot/board/rock5t/post-build.sh` | Installs extlinux, `fstab`, sshd, the hub units, and the RAUC certificate |
| `os/buildroot/board/rock5t/post-image.sh` | Builds the image, splices the Radxa bootloader, and signs the RAUC bundle |
| `os/buildroot/board/rock5t/rauc/version` | Version string written into the update bundle |
| `os/buildroot/board/rock5t/radxa-bootloader.bin` | Vendor loader copied from the Debian r7 image (16,744,448 bytes) |
| `os/buildroot/board/rock5t/rootfs-overlay/` | Firmware, network-wait drop-in, hub units, and RAUC |

The Debian r7 image used as the blob source is `C:\data\rock5t-image\rock-5t_bookworm_kde_r7.output_512.img`. Its root filesystem starts at byte `348127232`. Do not overwrite that file. The 32 GB card that once held Debian is not the boot card.

Buildroot itself is a separate clone, Buildroot 2026.08.1, at `/root/home-ai-os/buildroot` inside WSL Ubuntu 24.04. Downloads and the build output stay on the WSL ext4 disk (`/root/home-ai-os/dl` and `/root/home-ai-os/output`). Building with the output directory on `C:` is too slow and breaks sparse images.

## Build

Open a root shell in WSL. The Windows `PATH` that WSL inherits contains spaces and makes the build fail, so set a short `PATH` first.

```bash
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
cd /root/home-ai-os/buildroot
export BR2_DL_DIR=/root/home-ai-os/dl
export BR2_EXTERNAL=/mnt/c/data/github/home-ai-security/os/buildroot

make O=/root/home-ai-os/output home_ai_rock5t_defconfig
make O=/root/home-ai-os/output -j4
```

Log a long run inside WSL (`>/root/home-ai-os/build.log 2>&1`). Shell scripts in `os/buildroot` must stay LF. A Windows editor that saves CRLF makes `post-image.sh` fail.

The build produces `/root/home-ai-os/output/images/sdcard.img` (about 4.3 GB: two 2 GB root slots, a 32 MB boot partition, and a 256 MB `hub-data` placeholder) and `/root/home-ai-os/output/images/home-ai-update.raucb`. Growing that image onto a 128 GB card replaces the placeholder with a `hub-data` filesystem that fills the rest of the disk: `mkfs.ext4 -F -L hub-data -O ^orphan_file`. The WSL kernel (5.15) cannot mount an ext4 filesystem that has the `orphan_file` feature from e2fsprogs 1.47.4. The rootfs keeps the feature: it matches the Debian rootfs, and the vendor U-Boot can read it.

`post-image.sh` already splices `radxa-bootloader.bin` into `sdcard.img` at byte `32768`. After a rebuild, repeat that splice on `card.img` if the grown image was copied before the splice. The copy starts at byte `32768` and is at most `16744448` bytes, so it does not touch the GPT (bytes 0–512) or the first partition (16 MB).

## Card in the ROCK today

The card that is booted now is still the single-slot layout from before A/B. Its rootfs is one 2 GB partition at LBA `32896`, and `hub-data` starts at LBA `4227200` (UUID `a835e4a6-022a-41cf-a79f-7bd8bc79eb19`). Writing the new `sdcard.img` over that card would put the second root slot on top of the house data. Take a copy of `hub-data` first, then restore it onto the new data partition.

## Image layout

Sector size is 512. Partition numbers are fixed by `genimage.cfg` and by `boot.cmd`.

| # | Name | Location | Contents |
|---|---|---|---|
| | Loader gap | byte `32768` through `16777215` | Radxa DDR v1.22, vendor SPL, vendor U-Boot FIT. FIT magic `d00dfeed` is at absolute offset `0x800000` |
| 1 | `uboot-env` | 16 MB, 64 KB | Type `3DE21764-95BD-54BD-A5C3-4ABE786F38A8`. The A/B state is not stored here |
| 2 | `boot` | byte `16842752`, 32 MB, legacy bootable | FAT. `boot.scr`, `state.env`, `state.bak` |
| 3 | `rootfs-a` | 2 GB | Slot A. Same filesystem image as slot B on a fresh card |
| 4 | `rootfs-b` | 2 GB | Slot B |
| 5 | `hub-data` | the rest of the disk | Label `hub-data`. Home backup, Node, RKLLM, `hub.env`, Zigbee and Z-Wave data |

`/lib` on a rootfs is a symlink to `usr/lib`. `debugfs` does not follow it, so firmware added with `debugfs` has to be written under `/usr/lib/firmware`.

## Boot

The green LED next to the USB-C jack is the hardwired power LED. A dark HDMI port during early boot only means the console is still serial. After the vendor loader starts, HDMI is the `vidconsole`.

The vendor U-Boot environment (from the Debian FIT) is what this board runs:

- `bootcmd=run distro_bootcmd; boot_fit; bootrkp`
- `bootdelay=0`, baud `1500000`, consoles `serial,vidconsole`
- `fdtfile=rockchip/rk3588-rock-5t.dtb`
- `boot_targets=usb0 mmc1 nvme0 nvme1 mmc0 mtd2 mtd1 mtd0 pxe dhcp`
- Extlinux is loaded with `sysboot` from `${prefix}extlinux/extlinux.conf`, prefixes `/` and `/boot/`

`distro_bootcmd` scans partitions marked legacy-bootable, then falls back to partition 1. Only the FAT `boot` partition is bootable, so that is the one scanned. It has no extlinux file. U-Boot finds `boot.scr` and runs it. The script loads `state.env`, subtracts one attempt from the first slot that still has attempts, writes the new count back, and loads `/boot/Image` and `/boot/rk3588-rock-5t.dtb` from partition 3 (`rootfs-a`) or partition 4 (`rootfs-b`). The kernel command line sets `root=PARTLABEL=rootfs-a` or `rootfs-b` and `rauc.slot=A` or `B`. `console=tty1` is what puts the console on HDMI.

The vendor U-Boot was built without `setexpr`, and its `saveenv` does not target the `uboot-env` partition. The attempt counters are the text file `state.env` (`BOOT_ORDER`, `BOOT_A_LEFT`, `BOOT_B_LEFT`). `state.bak` is the previous copy. A fresh card starts at `BOOT_ORDER=A B` and three attempts on each slot.

Partition 1 is the 64 KB environment area and is not bootable. The compiled `partitions=` variable is an Android GPT layout used only by `bootrkp`. `boot.scr` ends in `booti` or `reset`, so control does not reach `bootrkp`. The extlinux file is still installed on each rootfs for a manual boot of slot A. The normal path does not read it.

`extlinux.conf` on the image:

```
label Home AI
  linux /boot/Image
  devicetree /boot/rk3588-rock-5t.dtb
  append root=PARTLABEL=rootfs-a rootwait rw earlycon console=ttyFIQ0,1500000n8 console=ttyS2,1500000n8 console=tty1 rauc.slot=A
```

A mainline U-Boot 2025.01 built with `rock5b-rk3588_defconfig` does not start this board. ROCK 5T has no upstream defconfig. Replacing only the DDR blob with `rk3588` TPL v1.22 and keeping the mainline SPL still left the board on the power LED. The loader that works is the whole vendor gap from the Debian r7 image: DDR v1.22, vendor SPL `U-Boot SPL rk2410-2017.09-63-39cd993-gfa7c5a2`, and the vendor U-Boot FIT. `post-image.sh` writes that blob. The defconfig still builds mainline U-Boot so genimage has a file to place; the post-image step replaces it.

The kernel is Radxa `linux` `04e2d04ea6ba8ecc18077af072cbab9b7c38296c`, defconfig `rockchip_linux`, device tree `rockchip/rk3588-rock-5t`. The booted tree is `rk3588-rock-5t.dtb`. The industrial tree (`rk3588-rock-5t-industrial.dts`) is not the one the boot script loads.

## System update

A system update replaces the rootfs that is not running. `hub-data` is not in the bundle, so pairings, `hub.env`, and the model stay put. The version string is `os/buildroot/board/rock5t/rauc/version`. The first image is `1.0`.

On a booted A/B card:

```sh
rauc install /mnt/hub-data/home-ai-update.raucb
reboot
```

`rauc install` writes the bundle into the inactive slot and sets `BOOT_ORDER` so that slot is tried first, with three attempts. The next boot decrements that counter before starting the kernel. If the new slot reaches `multi-user.target`, `rauc-mark-good.service` runs `rauc status mark-good` and the counter returns to 3. If the kernel never gets that far, the counter stays down. After three failed boots the script skips that slot and starts the previous one.

A hang does not decrement anything until the board is power-cycled or rebooted. Three power cycles of a slot that never marks itself good fall back to the other slot.

The signing key is created on the first image build at `os/buildroot/board/rock5t/rauc/development-key.pem`. It is not part of the rootfs and it is not committed. A bundle signed by another key is rejected. The certificate that matches this key is installed at `/etc/rauc/ca.cert.pem`.

Python and the OpenCV libraries have to be inside the rootfs image that the bundle carries. Copying them onto a running card does not put them into the next update.

## Fixes that make the hardware match the Debian card

### Ethernet

Both onboard NICs are RTL8125B, driven by the built-in `r8169` (`CONFIG_R8169=y`). `enP3p49s0` (`00:48:54:21:90:1c`) is the cabled port and links at 2.5 Gbps. `enP4p65s0` (`00:48:54:21:90:1d`) is the second port and stays down with no cable. The PHY can report link up while the MAC still has no firmware and passes no packets.

`rtl8169_open` requests `rtl_nic/rtl8125b-2.fw` after the rootfs is mounted, so the file on disk is enough. It is 3328 bytes, header `rtl8125b-2_0`, and is installed at `rootfs-overlay/usr/lib/firmware/rtl_nic/rtl8125b-2.fw`. systemd-networkd matches `e*` (`/etc/systemd/network/e*.network`, `DHCP=ipv4`), which covers `enP3p49s0`. The DHCP client identity changed with this image, so the old `10.0.0.83` reservation does not follow. The address in use is `10.0.0.85`. Reserving `00:48:54:21:90:1c` brings `.83` back if that address is wanted.

`linux.fragment` also lists `CONFIG_EXTRA_FIRMWARE` for the same file. That bake-in was not built. The running kernel loads the file from `/usr/lib/firmware`. Leave the fragment unused unless a future boot probes the NIC before the rootfs is mounted. `CONFIG_EXTRA_FIRMWARE_DIR` points at a `/mnt/c/...` path and only makes sense for a kernel compile inside this WSL distro.

### Network wait

`home-ai-hub.service` is `After=` and `Wants=network-online.target`, which starts `systemd-networkd-wait-online`. With no timeout the job sits on the console at "no limit", and the uncabled second port fails the job even after the cabled port has an address. The drop-in `rootfs-overlay/etc/systemd/system/systemd-networkd-wait-online.service.d/timeout.conf` caps it:

```
[Service]
TimeoutStartSec=20
ExecStart=
ExecStart=/usr/lib/systemd/systemd-networkd-wait-online --timeout=15 --any
```

A good boot prints `Finished Wait for Network to be Configured` in a few seconds and reaches `multi-user.target`.

### Hub Python

The virtualenv on `hub-data` was created on Debian Bookworm: Python 3.11.2, `pyvenv.cfg` `home=/usr/bin`, and wheels tagged `cp311` (including `opencv-python`, `torch`, `av`, and `numpy`). The Buildroot image's `/usr/bin/python3` is 3.14. The venv's `bin/python3` pointed at that interpreter, so `lib/python3.11` was invisible and the unit crash-looped on `ModuleNotFoundError: uvicorn`.

The running rootfs has Debian CPython 3.11.2 copied from the r7 image, plus its standard library and the libraries that binary needs:

- `/usr/bin/python3.11`
- `/usr/lib/python3.11/`
- `/usr/lib/libpython3.11.so.1.0`
- `libbz2.so.1.0`, `libcrypt.so.1`, `liblzma.so.5`, `libsqlite3.so.0`

`/mnt/hub-data/home-ai-security/.venv/bin/python3` points at `/usr/bin/python3.11`. `pyvenv.cfg` was left as Debian wrote it. The board already had `libexpat.so.1`, `libz.so.1`, `libssl.so.3`, `libcrypto.so.3`, `libffi.so.8`, and `libuuid.so.1`. Do not replace the board `libc` with Debian's.

These files are on the live rootfs. They are not in `rootfs-overlay` and they are not in `sdcard.img` / `card.img`. A later rootfs write from either image removes them and the hub goes back to the 3.14 crash loop. Recreating the venv with Buildroot 3.14 does not reuse the installed `cp311` wheels. Copy the same interpreter back, or add it to the overlay before the next image build.

### OpenCV libraries

`requirements.txt` installs `opencv-python` (the Qt/X11 build). After `uvicorn` imported, startup reached `import cv2` and failed on `libxcb.so.1`. The closure copied from the Debian rootfs into `/usr/lib` is:

`libxcb.so.1`, `libX11.so.6`, `libXext.so.6`, `libXau.so.6`, `libXdmcp.so.6`, `libGL.so.1`, `libGLdispatch.so.0`, `libGLX.so.0`, `libglib-2.0.so.0`, `libgthread-2.0.so.0`, `libpcre2-8.so.0`, `libICE.so.6`, `libSM.so.6`, `libbsd.so.0`, `libmd.so.0`, `libuuid.so.1`.

`import cv2` then reports `cv2 5.0.0`. The same warning as Python applies: these libraries are only on the live rootfs. With them in place the hub stays up, listens on `https://0.0.0.0:8443` and `http://0.0.0.0:8080`, and opens the driveway camera. The Z-Wave service listens on `127.0.0.1:3091`. Zigbee is the CH341 stick at `/dev/ttyUSB0`. Z-Wave is the Zooz 800 stick at `/dev/ttyACM0`.

### Bluetooth

The onboard radio enumerates as USB `13d3:3572`, not as an SDIO node. `btusb` is built in (`CONFIG_BT_HCIBTUSB=y`), so it cannot be `rmmod`ed. The kernel asks for `rtl_bt/rtl8852bu_fw.bin` and `rtl_bt/rtl8852bu_config.bin`. Both came from the Debian image. The config Debian ships is a symlink to `rtl8761bu_config.bin`, a 6-byte file `55 ab 23 87 00 00`. Copying the symlink without that target makes the probe log `cfg_sz -2`. The overlay stores the 6-byte file itself as `usr/lib/firmware/rtl_bt/rtl8852bu_config.bin` (101277-byte `rtl8852bu_fw.bin` beside it), so a future image has a real file.

After the USB interface is unbound and bound again, `dmesg` reports `cfg_sz 6, total sz 65603` and `fw version 0x04479301`, and `/sys/class/bluetooth/hci0` exists. Unbind both interfaces in one shot and the second write returns "No such device" because the first unbind already removed the device. Rebind `2-1.3:1.0` only.

### USB and USB-C

USB-A host (XHCI, EHCI, OHCI), `CONFIG_USB_ACM`, and `CONFIG_USB_SERIAL_CH341` are built in. The Zigbee and Z-Wave sticks come up with the image as built. USB-C is the FUSB302 on I2C (`fcs,fusb302`, DisplayPort alt mode). `CONFIG_TYPEC`, `TYPEC_TCPM`, `TYPEC_FUSB302`, `TYPEC_DP_ALTMODE`, `USB_DWC3_DUAL_ROLE`, and `PHY_ROCKCHIP_USBDP` are built in. No extra firmware. The console line "Hardware activated USB gadget" is the dual-role gadget, which is expected.

HDMI already works with the vendor loader: `CONFIG_DRM_ROCKCHIP`, `SND_SOC_ES8316`, and `SND_SOC_ROCKCHIP_HDMI` are built in.

## Still different from the Debian image

These were identified on the running board and are not fixed in the image.

- **Wi-Fi.** The booted `rk3588-rock-5t.dtb` has Wi-Fi/Bluetooth pinctrl only. It has no `&sdio` node, and both `&sdhci` and `&sdmmc` are `no-sdio`. The kernel's `rtw89` is the PCIe 8852CE module (`CONFIG_RTW89_8852CE`). There is no 8852B/8852BE/8852BS option in the config, and `CONFIG_BT_HCIUART_RTL` and `CONFIG_BT_HCIBTSDIO` are off. Debian's out-of-tree `rtl8852bu` DKMS module was not installed. `regulatory.db` is also missing, so `cfg80211` logs a firmware failure at boot.
- **NPU.** `CONFIG_ROCKCHIP_RKNPU` is enabled by the Radxa defconfig. `linux.fragment` sets `CONFIG_RKNPU` and `CONFIG_RKNPU_PROC_FS`, which are the wrong symbol names, so the procfs option never applies. RKNN userspace libraries are not in the rootfs. The RKLLM model and `librkllmrt.so` are on `hub-data`.
- **Hardware video decode.** The hub logs `Hardware decoder idle: No module named 'gi'`. The GStreamer introspection package is not installed.
- **Cloud Link.** The hub logs that `link.pem` is missing and the relay stays disconnected. The certificate belongs on `hub-data` with the rest of the Cloud Link material. Do not generate a replacement as part of an image rebuild.

Harmless boot lines on this board: `vendor_storage` returning `-1`, `fsck` after an unclean power-off, OP-TEE probe `-22`, and SCMI protocol 17 inactive.

## Writing the card

Confirm the disk identity immediately before any write. On this PC, disk 0 is the 512 GB KIOXIA NVMe (`C:`). The SD reader is a USB disk whose `Get-Disk` size is exactly `125671833600` and whose name matches the SD/MMC reader. `Win32_DiskDrive` reports a size a few megabytes smaller; use `Get-Disk`. Removable media cannot be set offline. A raw write needs an elevated handle. Do not dismount the volume before the write; an earlier write that dismounted first came out corrupt.

The card in the board is the old single-slot layout. The next `make` builds the A/B layout instead, and that image's second root slot overlaps the existing `hub-data`. Copy `hub-data` off before a full-card write, then restore it onto the new data partition. Python 3.11 and the X11/GL libraries are still only on the live rootfs. The Bluetooth firmware is in `rootfs-overlay`, so the next image includes it. Python and the OpenCV libraries have to be added to the overlay before a bundle can carry them.

`hub-data` holds `hub.env`, the Zigbee database, and the Z-Wave keys. A rootfs update must not format that partition. Door sensors stay paired. The hub process keeps door state in memory, so leave a running hub up unless the unit is crash-looping and has to be repaired.
