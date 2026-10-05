# Next sync: settings isolation in the test session

Open item for the next upstream sync. Fix it, then delete this file and the
README pointer to it.

## Summary

The test session isolates `XDG_CONFIG_HOME` for `cosmic-comp` and the tiling
applet so that `tiling_engine = Scrolling` never reaches the distribution
compositor. The README says only the compositor's own settings are isolated.
In practice the compositor reads more than `com.system76.CosmicComp` from that
directory, so the test session silently loses user settings.

Found on two Pop!_OS 26.04 hosts (COSMIC epoch-1.9.0, fork `main` `68749ee`).

## Problems

1. **The compositor reads other namespaces from the isolated directory.**
   `cosmic-comp` loads these through `XDG_CONFIG_HOME`:
   - `com.system76.CosmicSettings.Shortcuts` (`cosmic_settings_config::shortcuts`)
   - `com.system76.CosmicSettings.WindowRules` (`cosmic_settings_config::window_rules`)
   - `com.system76.CosmicTk` (`cosmic::config::CosmicTk`, `src/config/mod.rs`)
   - the COSMIC theme: `com.system76.CosmicTheme.Mode`, `.Dark`, `.Light`
     (`theme::watch_theme`, `src/theme.rs`)

   With an empty isolated directory the session falls back to system defaults:
   custom shortcuts, window rules and the theme are lost.

2. **`com.system76.CosmicComp` is not seeded from the real config.** The
   launcher writes only `autotile` and `tiling_engine`. Real keys such as
   `xkb_config` (keyboard layout and options), `keyboard_config` (NumLock),
   `descale_xwayland` and input settings are missing in the test session.

3. **Settings made inside the test session do not apply.** COSMIC Settings
   runs with the real `XDG_CONFIG_HOME` and writes there. The isolated
   compositor does not see the change.

4. **Old installs keep a stale snapshot.** Installs from before the
   "share the user's real configuration" change still have a full
   `.cosmic-scrolling/session-config` (COSMIC namespaces from that date plus
   application directories, for example Electron app profiles, about 180 MB on
   one host). The current launcher keeps using the stale COSMIC namespaces
   from it, and nothing cleans up the application directories.

## Proposed fix

Preferred: remove the need for isolation. Let the prototype read its engine
choice from a key or namespace that the distribution compositor ignores (for
example `com.system76.CosmicComp.Scrolling/v1/tiling_engine`, or a separate
`scrolling_tiling_engine` key), with `Classic` as the fallback. Then
`cosmic-comp` and the applet can use the real `XDG_CONFIG_HOME`, and the
`session-bin` wrappers and `session-config` can go.

If isolation stays, `start-scrolling-session.sh` should on every launch:

- symlink every `$REAL_XDG_CONFIG_HOME/cosmic/<namespace>` except
  `com.system76.CosmicComp` into `session-config/cosmic/` (replace stale
  directories, keep existing correct links);
- refresh `com.system76.CosmicComp/v1` from the real files, then overlay only
  the session's `tiling_engine` and `autotile`;
- warn about (or move aside) non-COSMIC directories left by old installs.

Workaround applied by hand on both hosts: the layout above (symlinks plus a
refreshed `CosmicComp` copy). On a host with a running test session, a new
`cosmic/` tree was built beside the old one and swapped in by rename, so the
live compositor's inotify watches stayed on the old tree.

## Checks after the fix

- `uninstall.sh --purge-config` removes the symlinks and not their targets.
- Custom shortcuts, theme, keyboard layout and NumLock work in the test session.
- After logout, normal COSMIC still never reads `tiling_engine = Scrolling`.
- Update the README sentence about which settings are isolated.
