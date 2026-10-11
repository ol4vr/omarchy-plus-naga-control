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

## Hidden desktop startup

`naga-control --hidden` creates the normal tray integration without showing,
focusing, or assigning the main window. The GUI singleton uses a separate
non-activating probe for this mode, so a repeated login launch cannot reveal a
hidden window or create a second GUI process. A normal `naga-control` launch
still restores and focuses the existing window. Hugin integrates the hidden
command through its existing Omarchy+ login helper; Naga Control owns no extra
daemon or desktop-autostart file.

## Discovery and activation

The default configuration is no-write discovery. Starting the service in this
state may connect to OpenRazer and read supported properties. It does not set
device mode, apply profiles, open/grab event nodes, create remapping sessions,
or repair mode drift. D-Bus snapshots distinguish device reads, the cached
poll-rate observation, and unavailable lighting readback.

`remapping_enabled = true` is a separate, explicit software-input opt-in. It
may open and grab only the discovered Naga `1532:00e7` or `1532:00e8` event
nodes and create uinput replacement devices when the mouse is already verified
in software mode. It does not enable `hardware_writes`, apply the saved DPI,
polling, scroll, power, or lighting settings, or correct device-mode drift.
Fresh configurations disable both former DPI buttons. Enabling remapping is
rejected if either still has a `dpi_stage_up` or `dpi_stage_down` action.

`hardware_writes = true` is a separately reviewed configuration transition.
The first transition is permitted only when one current snapshot contains all
DPI stages and active stage, scroll mode/options/toggles, a separately verified
poll rate, idle timeout, and low-battery threshold; the active profile exactly
matches those observations; the desired device mode matches the observed mode;
and `lighting_writes` remains false. Calibration adopts readable values without
changing the write gate. OpenRazer's daemon-cached poll-rate property is not
verification, so the current Hugin cohort deliberately remains read-only until
that discrepancy has a safe, independently verified resolution.

The session service additionally exposes `SetDpi(x, y)` for one owner-requested
DPI change through the same serialized, topology-fenced OpenRazer worker. This
is a narrow explicit action, not permission to apply a profile: it leaves
`hardware_writes`, the configuration revision, saved DPI stages, mappings,
remapping state, and every lighting zone unchanged. The method returns the
fresh observed snapshot so callers can verify the write. Omarchy+ Mouse Control
must use this method and must not access OpenRazer independently.

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

An existing owned stage or active installation is updated through the same
installer rather than removed manually:

```text
python scripts/owned_install.py --home "$HOME" upgrade \
  --bundle dist/Naga-Control-0.5.0-hugin-x86_64.tar.xz --sha256 <reviewed-sha256>
```

Upgrade first verifies and extracts the new bundle without changing the active
installation. It refuses unless `hardware_writes`, `remapping_enabled`, and
every profile's `lighting_writes` are false. For an active installation it
preserves whether the unit was running, stops that single unit before replacing
manifest-owned files, reloads the user manager, and starts the new version only
when the old version was running, then confirms the unit remains active. Any
replacement, reload, start, or immediate active-state failure restores the old
files and state, reloads again, and restarts the former working version.
Configuration and profiles under `~/.config/naga-control/` are never replaced.
The old staged payload is removed only after successful replacement.

A separately authorized pilot may run the `activate` subcommand. Activation
refuses a configuration with hardware, remapping, or lighting writes enabled,
atomically installs only manifested user integration, runs `systemctl --user
daemon-reload`, and starts but never enables `naga-control.service`. A failed
start stops the unit and removes every file written by that attempt. It never
installs udev rules or changes groups; the existing device-scoped access must
be reviewed separately.

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

The uninstalled NAGA-CONTROL-2 central integration candidate implements the
source-scoped design as follows:

1. keyd keeps `CapsLock = F13` for normal physical keyboards;
2. keyd excludes exactly `1532:00e7`, `1532:00e8`, and Naga Control's verified
   virtual keyboard identity `4e43:0001`;
3. Hyprland binds the `F13` keysym only for the inclusive
   `keyd-virtual-keyboard` device and dispatches press/release through the
   Omarchy+ source-aware PTT controller, not through a global keycode binding;
4. service failure releases grabs so pointer/buttons pass through, while the
   compositor source filter continues rejecting physical Naga F13; and
5. an on-demand, non-enabled user guard validates keyd's complete sysfs
   identity and Hyprland device identity, snapshots eligible physical Caps Lock
   interfaces, serializes press/release, and forces PTT release if a verified
   source disappears or the physical keyboard inventory changes during a hold.

keyd intentionally merges all normal wildcard-managed keyboards into one
virtual source, so the compositor cannot recover which normal keyboard emitted
the Caps Lock event. All such normal keyboards are authorized by this contract;
the two Naga products and Naga Control virtual keyboard are excluded before the
merge. Any physical keyboard disappearance during a hold causes a conservative
release. Logitech remains under the existing wildcard policy and is neither
specially selected nor excluded.

No identities may be added from guesses. The two physical IDs and virtual ID
must be re-observed during the separately approved pilot. Until the owned
Discord PTT path is accepted, reconciled, and passes live source, press/release,
disconnect, fail-open, multiple-keyboard, and Logitech regression checks, live
pilot readiness remains blocked even though its isolated fixtures cover those
paths and the application build itself is reviewable.

## Permissions and known packaging limits

The proposed udev rules are device-scoped `uaccess` for only the two Naga
product IDs (`1532:00e7` wired and `1532:00e8` HyperSpeed), session-wide
`uaccess` for `/dev/uinput`, and no virtual-event-node grant. They require a
privileged, separate approval. No Logitech ID, input-group membership, or broad
input rule is included. Reloading the rules does not grant an existing Naga
node retroactively; reconnect the selected Naga transport after reload. The
user service remains unprivileged and is not enabled persistently.

The selected artifact is an extracted AppDir tar.xz. It does not need FUSE2.
The runtime lock is Hugin x86_64-specific; this is not a bit-for-bit build or an
Ubuntu portability claim. `dbus-python` and `evdev` build from locked source
archives, but their isolated build-tool environment is not yet hermetically
locked. The archive hash and bundled distribution inventory establish the
exact tested artifact.

## Pilot recovery sequence

Keep the Logitech mouse connected. Before activation, record input-node
identities, keyd mapping, OpenRGB's seven controllers, and OpenRazer read-only
state. Start in discovery-only mode and verify there are no grabs, virtual
devices, hardware-setting writes, or RGB changes. Install the exact scoped udev
rule only under separate approval, reconnect the Naga, set both former DPI
buttons to Disabled in the GUI, and then use **Enable remapping**. Leave
`hardware_writes = false` and `lighting_writes = false` throughout this pilot.

On any pointer loss, conflicting grab, unexpected F13 PTT, RGB change, or daemon
conflict: use the Logitech recovery pointer, run `systemctl --user stop
naga-control.service`, and set `remapping_enabled = false` in
`~/.config/naga-control/config.toml` before starting discovery again. Confirm
physical Naga fail-open behavior and leave OpenRazer/OpenRGB/keyd untouched. Do
not restart OpenRGB or write raw HID reports during recovery.
