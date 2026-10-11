#!/bin/sh

set -eu

SCRIPT_PATH=$(readlink -f -- "$0")
PROJECT_ROOT=$(CDPATH= cd -- "$(dirname -- "$SCRIPT_PATH")" && pwd -P)
SUITE_ROOT=$(dirname -- "$PROJECT_ROOT")
APPLET_STATE="$SUITE_ROOT/.cosmic-scrolling"
APPLET_PREFIX="$APPLET_STATE/prefix"

# The suite installer records the compositor's Cargo build profile in its
# manifest. Standalone compositor checkouts have no manifest and always use
# target/debug.
COMPOSITOR_PROFILE=debug
if [ -f "$APPLET_STATE/manifest" ]; then
    MANIFEST_PROFILE=$(grep '^profile=' "$APPLET_STATE/manifest" || true)
    case "$MANIFEST_PROFILE" in
        profile=debug|profile=fastdebug) COMPOSITOR_PROFILE=${MANIFEST_PROFILE#profile=} ;;
    esac
fi
COMPOSITOR="$PROJECT_ROOT/target/$COMPOSITOR_PROFILE/cosmic-comp"

# The test session shares the user's real configuration with normal COSMIC.
# This compositor keeps its engine choice in a fork-specific key that the
# distribution compositor and applet do not read.
COMP_CONFIG="${XDG_CONFIG_HOME:-$HOME/.config}/cosmic/com.system76.CosmicComp/v1"

if [ ! -x "$COMPOSITOR" ]; then
    COMPOSITOR_PROFILE_ARG=""
    if [ "$COMPOSITOR_PROFILE" = fastdebug ]; then
        COMPOSITOR_PROFILE_ARG="--profile $COMPOSITOR_PROFILE"
    fi
    echo "Scrolling test compositor is missing: $COMPOSITOR" >&2
    echo "Build it with: cd $PROJECT_ROOT && cargo build --locked $COMPOSITOR_PROFILE_ARG" >&2
    exit 1
fi

if ! SESSION_LAUNCHER=$(command -v start-cosmic); then
    echo "The system COSMIC session launcher is missing: start-cosmic" >&2
    exit 1
fi

# This is a full login session, not a nested compositor. Starting another
# cosmic-session inside a running desktop can replace its user-manager state.
if [ -n "${WAYLAND_DISPLAY-}" ] || [ -n "${DISPLAY-}" ]; then
    echo "Start COSMIC Scrolling Test from the greeter after logging out." >&2
    echo "For a nested test, run the compositor directly with COSMIC_BACKEND=x11." >&2
    exit 1
fi

# The suite installer owns this optional prefix. A standalone compositor
# checkout continues to use the distribution applet.
USE_PRIVATE_APPLET=false
if [ -e "$APPLET_STATE/manifest" ]; then
    if ! grep -qxF 'owner=cosmic-scrolling-prototype-v1' "$APPLET_STATE/manifest" \
        || [ ! -x "$APPLET_PREFIX/bin/cosmic-applet-tiling" ] \
        || [ ! -f "$APPLET_PREFIX/share/applications/com.system76.CosmicAppletTiling.desktop" ]; then
        echo "Private applet installation is incomplete; rerun $SUITE_ROOT/install.sh --build-only." >&2
        exit 1
    fi
    USE_PRIVATE_APPLET=true
fi


mkdir -p "$COMP_CONFIG"

# Start in Scrolling on first launch. Preserve any later engine choice.
if [ ! -e "$COMP_CONFIG/scrolling_tiling_engine" ]; then
    printf '%s\n' Scrolling >"$COMP_CONFIG/scrolling_tiling_engine"
fi

# start-cosmic imports the launch environment into the persistent user systemd
# manager. Restore the pre-session values on logout so the private paths cannot
# leak into a later normal COSMIC session.
ORIGINAL_PATH=$PATH
ORIGINAL_XDG_DATA_DIRS=${XDG_DATA_DIRS-}
ORIGINAL_XDG_DATA_DIRS_SET=${XDG_DATA_DIRS+x}
ORIGINAL_RUST_LOG=${RUST_LOG-}
ORIGINAL_RUST_LOG_SET=${RUST_LOG+x}
ORIGINAL_SCROLLING_TILING=${COSMIC_SCROLLING_TILING-}
ORIGINAL_SCROLLING_TILING_SET=${COSMIC_SCROLLING_TILING+x}
ORIGINAL_SCROLLING_SESSION=${COSMIC_SCROLLING_SESSION-}
ORIGINAL_SCROLLING_SESSION_SET=${COSMIC_SCROLLING_SESSION+x}

restore_user_manager_environment() {
    command -v systemctl >/dev/null 2>&1 || return 0
    systemctl --user set-environment "PATH=$ORIGINAL_PATH" >/dev/null 2>&1 || true
    if [ "$USE_PRIVATE_APPLET" = true ]; then
        if [ -n "$ORIGINAL_XDG_DATA_DIRS_SET" ]; then
            systemctl --user set-environment "XDG_DATA_DIRS=$ORIGINAL_XDG_DATA_DIRS" >/dev/null 2>&1 || true
        else
            systemctl --user unset-environment XDG_DATA_DIRS >/dev/null 2>&1 || true
        fi
    fi

    if [ -n "$ORIGINAL_RUST_LOG_SET" ]; then
        systemctl --user set-environment "RUST_LOG=$ORIGINAL_RUST_LOG" >/dev/null 2>&1 || true
    else
        systemctl --user unset-environment RUST_LOG >/dev/null 2>&1 || true
    fi
    if [ -n "$ORIGINAL_SCROLLING_TILING_SET" ]; then
        systemctl --user set-environment "COSMIC_SCROLLING_TILING=$ORIGINAL_SCROLLING_TILING" >/dev/null 2>&1 || true
    else
        systemctl --user unset-environment COSMIC_SCROLLING_TILING >/dev/null 2>&1 || true
    fi
    if [ -n "$ORIGINAL_SCROLLING_SESSION_SET" ]; then
        systemctl --user set-environment "COSMIC_SCROLLING_SESSION=$ORIGINAL_SCROLLING_SESSION" >/dev/null 2>&1 || true
    else
        systemctl --user unset-environment COSMIC_SCROLLING_SESSION >/dev/null 2>&1 || true
    fi
}
trap restore_user_manager_environment EXIT

export COSMIC_SCROLLING_TILING=1
export COSMIC_SCROLLING_SESSION=1
SESSION_PATH="$PROJECT_ROOT/target/$COMPOSITOR_PROFILE"
if [ "$USE_PRIVATE_APPLET" = true ]; then
    SESSION_PATH="$APPLET_PREFIX/bin:$PROJECT_ROOT/target/$COMPOSITOR_PROFILE"
    export XDG_DATA_DIRS="$APPLET_PREFIX/share:${XDG_DATA_DIRS:-/usr/local/share:/usr/share}"
fi
export PATH="$SESSION_PATH:$PATH"
export RUST_LOG="${RUST_LOG:-cosmic_comp=info}"

# Skip start-cosmic's login-shell recursion so the development PATH above is
# preserved when cosmic-session launches cosmic-comp. Keep this shell as the
# parent so its EXIT trap can restore the user manager environment on logout.
"$SESSION_LAUNCHER" --in-login-shell
