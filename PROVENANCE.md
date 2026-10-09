# Source provenance and ownership

This repository is the Omarchy+-maintained Naga Control application. Its
complete imported history is preserved from `Rainexn0b/naga-control` through
commit `f48b3a4374b27571ab2afabe8e999595483e138a` (tree
`5367dd72e875ef578eaa9bbe208ee2d1a5aa4bdf`). That commit is the immutable
owned-source baseline; it was not reconstructed from an archive or shallow
checkout. Original authorship, copyright notices, and the `GPL-2.0-only`
license in `LICENSE` remain intact.

The matching experimental OpenRazer cohort is external and is pinned at
`Rainexn0b/openrazer` commit
`26b0eeb5ed70d638fa3528851adcd5e58369a7f5`. OpenRazer's kernel driver,
daemon, and Python client are not vendored here. Hugin's separately installed
cohort remains the runtime authority.

## Omarchy+ delta after the import

- make fresh and legacy configuration discovery-only (`hardware_writes = false`)
- require exact agreement with complete DPI, scroll, independently verified
  polling, idle-time, and battery-threshold reads before an explicit transition
  permits hardware writes or input grabs
- make all three lighting-zone writes independently opt-in and default-off
- reserve F13 from generated key/key-combo output
- fix Qt model-subscriber and tray-menu ownership, including deterministic
  posted-event draining in the order-sensitive overview test
- lock the Hugin runtime inputs and add a deterministic FUSE-free AppDir bundle
- add stage-only, explicit activation, manifest removal, and rollback tooling
- add isolated tests and the integration/recovery contract

This source is accepted as an Omarchy+ development candidate. It is not a
published release, approved for live activation, or an accepted BASE component.
The first Omarchy+ commit retains this baseline reference, and the central
repository records that commit as the exact owned-source candidate revision.
