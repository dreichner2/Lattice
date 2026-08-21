#!/bin/zsh

set -euo pipefail

script_dir=${0:A:h}
library_root=${script_dir:h}
app_path="$library_root/CS Library.app"
native_root="$library_root/native"
build_root=$(/usr/bin/mktemp -d "${TMPDIR:-/tmp}/cs-library-app.XXXXXX")

cleanup() {
  /bin/rm -rf "$build_root"
}
trap cleanup EXIT

if [[ -e "$app_path" && ! -d "$app_path/Contents" ]]; then
  print -u2 "Refusing to replace a non-app path: $app_path"
  exit 1
fi

/bin/rm -rf "$app_path"
/bin/mkdir -p "$app_path/Contents/MacOS" "$app_path/Contents/Resources"
/bin/cp "$native_root/Info.plist" "$app_path/Contents/Info.plist"

for required_source in \
  "$native_root/CSLibraryApp.swift" \
  "$native_root/ImmersiveReaderCoordinator.swift" \
  "$native_root/NativePDFReaderController.swift" \
  "$native_root/NativePDFReaderUI.swift" \
  "$native_root/NativePDFReaderState.swift" \
  "$native_root/ImmersiveEPUB.js"; do
  if [[ ! -f "$required_source" ]]; then
    print -u2 "Missing native reader source: $required_source"
    exit 1
  fi
done

target_arch=$(/usr/bin/uname -m)
/usr/bin/swiftc \
  -O \
  -target "${target_arch}-apple-macosx13.0" \
  -framework AppKit \
  -framework PDFKit \
  -framework WebKit \
  "$native_root/CSLibraryApp.swift" \
  "$native_root/ImmersiveReaderCoordinator.swift" \
  "$native_root/NativePDFReaderController.swift" \
  "$native_root/NativePDFReaderUI.swift" \
  "$native_root/NativePDFReaderState.swift" \
  -o "$app_path/Contents/MacOS/CS Library"

iconset="$build_root/AppIcon.iconset"
base_icon="$build_root/AppIcon.png"
/bin/mkdir -p "$iconset"
if /usr/bin/sips -s format png "$native_root/AppIcon.svg" --out "$base_icon" >/dev/null 2>&1; then
  for specification in \
    "16 icon_16x16.png" \
    "32 icon_16x16@2x.png" \
    "32 icon_32x32.png" \
    "64 icon_32x32@2x.png" \
    "128 icon_128x128.png" \
    "256 icon_128x128@2x.png" \
    "256 icon_256x256.png" \
    "512 icon_256x256@2x.png" \
    "512 icon_512x512.png" \
    "1024 icon_512x512@2x.png"; do
    size=${specification%% *}
    filename=${specification#* }
    /usr/bin/sips -z "$size" "$size" "$base_icon" --out "$iconset/$filename" >/dev/null
  done
  /usr/bin/iconutil -c icns "$iconset" -o "$app_path/Contents/Resources/AppIcon.icns"
fi

/usr/bin/codesign --force --deep --sign - "$app_path" >/dev/null
/usr/bin/touch "$app_path"

print "Built $app_path"
