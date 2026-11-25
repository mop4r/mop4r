# Hi, I'm mop4r

Open-source tools, embedded Linux ports, and hardware experiments.

## Featured Projects

### [TagTeam](https://github.com/mop4r/tagteam) · [Site](https://mop4r.github.io/tagteam/)
One conversation across **Claude Code**, **Gemini (Antigravity app & `agy` CLI)**, and **Grok CLI**. Two-way native session sync through hooks, shared `CLAUDE.md`/skills/plugins/MCP servers, and automatic 5-line handoff notes when a usage limit approaches 95%. Pure Python standard library, 100% local.

### [tvbox-rk3228a-armbian](https://github.com/mop4r/tvbox-rk3228a-armbian)
**Armbian (Debian Trixie, kernel 6.18)** on a generic **Rockchip RK3228A / RK3229 TV box** (MXQ Pro 4K 5G, board `R29_5G_LP3 V3.0`): SD card auto-installer to eMMC (no maskrom needed), 4K HDMI black-screen fix, safe **DDR 660 MHz** with automatic fallback, crash diagnostics (`ramoops`/watchdog), and **Pi-hole + Unbound (DNS over TLS) + Tailscale** home server.

### [aquarius-gps-connect-linux](https://github.com/mop4r/aquarius-gps-connect-linux)
**Debian 13 (Trixie, armhf)** booting from microSD on an **Aquarius Connect 5.0** car GPS (**Allwinner A10 / sun4i**, board `MTC4553`, Mali-400, 800×480 touchscreen, RTL8188CUS Wi-Fi) without touching stock Android/iGO NAND. Turns the device into a **RetroArch** retro-gaming handheld (`cage`/Wayland) and **XFCE** touchscreen tablet with mainline U-Boot, custom DTS, safe 1104 MHz turbo, and `rtl8xxxu` DKMS Wi-Fi.

### [RarSeeker](https://github.com/mop4r/RarSeeker)
Python utility for browsing and searching the archived RARBG SQLite database by name, category, size, resolution, or IMDb ID.
