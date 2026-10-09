# Omarchy+ experimental integration contract

This document governs the owned Hugin build derived from the baseline in
`PROVENANCE.md`. It supersedes the upstream installer's automatic
`enable --now` behavior for Omarchy+ use. It does not authorize installation,
input access, service activation, OpenRazer changes, or hardware writes.

## Ownership boundaries

- OpenRazer owns Razer kernel/daemon access. Its observed DPI, stage, scroll,
  idle-time, threshold, battery, and firmware values are device reads. Its
  `poll_rate` property and lighting effect getters can be daemon persistence or
  cache; they are labelled as such and are not treated as direct hardware
  truth.
- Naga Control may own only the Naga `1532:00e7` or `1532:00e8` input nodes,
  one transport at a time, after explicit activation and complete discovery.
- keyd owns normal physical keyboards. The Naga products and Naga Control's
  virtual keyboard (`4e43:0001`) must be excluded from keyd. The Logitech
  fallback is never selected, grabbed, configured, or required by Naga Control.
- OpenRGB remains authoritative for RGB. `lighting_writes = false` is the
  default and remains required for the pilot. OpenRazer may expose/cache the
  Naga's thumb-grid, logo, and wheel zones, but Naga Control does not apply them.

## Discovery and activation

The default configuration is no-write discovery. Starting the service in this
state may connect to OpenRazer and read supported properties. It does not set
device mode, apply profiles, open/grab event nodes, create remapping sessions,
or repair mode drift. D-Bus snapshots distinguish device reads, the cached
poll-rate observation, and unavailable lighting readback.

`hardware_writes = true` is a separately reviewed configuration transition.
The first transition is permitted only when one current snapshot contains all
DPI stages and active stage, scroll mode/options/toggles, a separately verified
poll rate, idle timeout, and low-battery threshold; the active profile exactly
matches those observations; the desired device mode matches the observed mode;
and `lighting_writes` remains false. Calibration adopts readable values without
changing the write gate. OpenRazer's daemon-cached poll-rate property is not
verification, so the current Hugin cohort deliberately remains read-only until
that discrepancy has a safe, independently verified resolution.

## Staging, activation, and rollback

Build an AppDir with the normal builder, then create the Hugin-only bundle:

```text
python scripts/build_hugin_bundle.py build/appimage/AppDir \
  dist/Naga-Control-0.5.0-hugin-x86_64.tar.xz
python scripts/owned_install.py --home "$HOME" stage \
  --bundle dist/Naga-Control-0.5.0-hugin-x86_64.tar.xz --sha256 <reviewed-sha256>
```

Staging verifies the hash, rejects unsafe archive members, extracts below
`~/.local/opt/naga-control/<sha256>/`, and writes only its ownership manifest.
It does not place a user unit, D-Bus activation file, desktop file, udev rule,
or executable in an active search path. It never invokes systemctl or executes
the payload.

A separately authorized pilot may run the `activate` subcommand. Activation
refuses a configuration with hardware writes enabled, atomically installs only
manifested user integration, runs `systemctl --user daemon-reload`, and starts
but never enables `naga-control.service`. A failed start stops the unit and
removes every file written by that attempt. It never installs udev rules or
changes groups; the existing device-scoped access must be reviewed separately.

Removal refuses while the service is active and refuses to delete a modified
owned file. After an authorized stop, `remove` removes exact manifested user
integration; `--purge-stage` additionally removes the owned extracted bundle.
`~/.config/naga-control/` and all profiles are always preserved. Reinstalling
the independent Logitech fallback is never part of rollback.

## Input and F13/PTT safety

Naga Control rejects F13 as a generated key or key-combo output. This prevents
application mappings from synthesizing the current Discord PTT key. It does
not solve the physical Naga driver's F13 report when Naga Control is inactive,
failed, discovery-only, or deliberately fail-open. Therefore global compositor
F13 PTT is not safe for a live pilot.

The required source-scoped design is:

1. keyd keeps `CapsLock = F13` for normal physical keyboards;
2. keyd excludes exactly `1532:00e7`, `1532:00e8`, and Naga Control's verified
   virtual keyboard identity `4e43:0001`;
3. the Discord PTT bridge accepts F13 only from keyd's virtual keyboard source,
   not from a global Hyprland keycode binding or any Naga source;
4. service failure releases grabs so pointer/buttons pass through, while the
   source-filtered PTT bridge continues rejecting physical Naga F13.

No identities may be added from guesses. The two physical IDs and virtual ID
must be re-observed during the separately approved pilot. Until the owned
Discord PTT path has source filtering and fail-open tests, live pilot readiness
is blocked even though the application build itself is reviewable.

## Permissions and known packaging limits

The proposed udev rules are device-scoped `uaccess` for the two Naga product
IDs, session-wide `uaccess` for `/dev/uinput`, and read access for deterministic
`Naga Control *` virtual nodes. They require a privileged, separate approval.
No group membership is proposed. The user service is unprivileged and is not
enabled persistently. D-Bus activation is installed only during explicit
activation, never staging.

The selected artifact is an extracted AppDir tar.xz. It does not need FUSE2.
The runtime lock is Hugin x86_64-specific; this is not a bit-for-bit build or an
Ubuntu portability claim. `dbus-python` and `evdev` build from locked source
archives, but their isolated build-tool environment is not yet hermetically
locked. The archive hash and bundled distribution inventory establish the
exact tested artifact.

## Pilot recovery sequence

Keep the Logitech mouse connected. Before activation, record service inactivity,
input-node identities, keyd mapping, OpenRGB's seven controllers, and OpenRazer
read-only state. Activate in discovery-only mode and verify there are no grabs,
virtual devices, hardware-setting writes, or RGB changes. Do not set
`hardware_writes = true` until the complete-state and exact-match gates,
independent poll-rate verification, and source-scoped PTT prerequisite all pass.

On any pointer loss, conflicting grab, unexpected F13 PTT, RGB change, or daemon
conflict: stop only `naga-control.service`, confirm the Logitech fallback,
confirm physical Naga fail-open behavior, leave OpenRazer/OpenRGB/keyd untouched,
then remove manifested user integration. Do not restart OpenRGB or write raw
HID reports during recovery.
