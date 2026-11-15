#!/usr/bin/env bash
# Stub libraries so PySide6 can start on a machine with no display and no
# GL drivers.  Every stub returns 0 and does nothing: enough for
# QT_QPA_PLATFORM=offscreen, never enough for real drawing.  A tool for
# running the test suite here, and nothing else.
#
#   ./tools/build_qt_shims.sh
#   export QT_QPA_PLATFORM=offscreen
#   export LD_LIBRARY_PATH="$PWD/.venv/qt-shims"
#   .venv/bin/python tools/run_tests_parallel.py --workers 4
#
# It writes into .venv/, which is not kept between sessions, so the
# script itself lives out here and the shims are rebuilt when needed.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
QT_LIB="$ROOT/.venv/lib/python3.11/site-packages/PySide6/Qt/lib"
OUT="$ROOT/.venv/qt-shims"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
[ -d "$QT_LIB" ] || { echo "no Qt libraries at $QT_LIB" >&2; exit 1; }
mkdir -p "$OUT"

collect() {
  {
    for lib in "$QT_LIB"/libQt6*.so*; do nm -D --undefined-only "$lib" 2>/dev/null || true; done
    for folder in "$QT_LIB/../plugins" "$QT_LIB/plugins"; do
      [ -d "$folder" ] || continue
      find "$folder" -name '*.so' -print0 2>/dev/null |
        while IFS= read -r -d '' lib; do nm -D --undefined-only "$lib" 2>/dev/null || true; done
    done
  } | awk '{print $2}' | sort -u
}

group_of() {
  case "$1" in
    dbus_*)        echo "libdbus-1.so.3:LIBDBUS_1_3" ;;
    xkb_*)         echo "libxkbcommon.so.0:V_0.5.0" ;;
    glX*|gl[A-Z]*) echo "libGL.so.1:V_0.5.0" ;;
    egl*|EGL*)     echo "libEGL.so.1:V_0.5.0" ;;
    *) echo "" ;;
  esac
}

declare -A SYMS
while read -r sym; do
  [ -n "$sym" ] || continue
  bare="${sym%%@*}"
  group="$(group_of "$bare")"
  [ -n "$group" ] || continue
  SYMS["$group"]="${SYMS[$group]:-} $bare"
done < <(collect)

for group in "${!SYMS[@]}"; do
  soname="${group%%:*}"; version="${group##*:}"
  { echo "/* Stubs for $soname - they do nothing and return 0. */"
    for sym in ${SYMS[$group]}; do echo "long ${sym}(void) { return 0; }"; done
  } > "$WORK/stub.c"
  { echo "$version {"; echo "  global:"
    for sym in ${SYMS[$group]}; do echo "    $sym;"; done
    echo "  local: *;"; echo "};"
  } > "$WORK/stub.map"
  gcc -shared -fPIC -O1 -o "$OUT/$soname" -Wl,--version-script,"$WORK/stub.map" -Wl,-soname,"$soname" "$WORK/stub.c"
  printf '%-22s %4d stubs (version %s)\n' "$soname" "$(echo ${SYMS[$group]} | wc -w)" "$version"
done
echo "shims are in $OUT"
