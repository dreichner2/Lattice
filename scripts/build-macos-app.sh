#!/bin/zsh

set -euo pipefail

script_dir=${0:A:h}
library_root=${script_dir:h}
app_path="$library_root/Lattice.app"
native_root="$library_root/native"
ui_root="$library_root/ui"
server_source="$library_root/scripts/library_ui.py"
vault_source="$library_root/scripts/library_vault.py"
tutor_source="$library_root/scripts/lattice_tutor.py"
study_source="$library_root/scripts/study_lab.py"
tutor_vendor_root="$library_root/scripts/vendor"
storage_source="$library_root/scripts/move_library.py"
build_root=$(/usr/bin/mktemp -d "${TMPDIR:-/tmp}/cs-library-app.XXXXXX")
staged_app="$build_root/Lattice.app"
previous_app="$build_root/Previous Lattice.app"

cleanup() {
  /bin/rm -rf "$build_root"
}
trap cleanup EXIT

if [[ -e "$app_path" && ! -d "$app_path/Contents" ]]; then
  print -u2 "Refusing to replace a non-app path: $app_path"
  exit 1
fi

required_sources=(
  ReaderModels.swift
  LibraryIdentity.swift
  ReaderStore.swift
  ReaderBridge.swift
  MacUpdateChecker.swift
  MacUpdateInstaller.swift
  CSLibraryApp.swift
  ImmersiveReaderCoordinator.swift
  NativePDFReaderController.swift
  NativePDFReaderUI.swift
  NativePDFReaderState.swift
)
for source in $required_sources; do
  if [[ ! -f "$native_root/$source" ]]; then
    print -u2 "Missing native source: $native_root/$source"
    exit 1
  fi
done
for resource in \
  "$native_root/ImmersiveEPUB.js" \
  "$native_root/LibraryWorkspace.js" \
  "$native_root/Info.plist" \
  "$library_root/THIRD_PARTY_NOTICES.md" \
  "$server_source" \
  "$vault_source" \
  "$tutor_source" \
  "$study_source" \
  "$tutor_vendor_root/README.md" \
  "$tutor_vendor_root/pypdf-LICENSE" \
  "$tutor_vendor_root/pypdf/__init__.py" \
  "$storage_source" \
  "$ui_root/index.html" \
  "$ui_root/app.js" \
  "$ui_root/tutor.js" \
  "$ui_root/styles.css" \
  "$ui_root/tutor-styles.css" \
  "$ui_root/study-lab.html" \
  "$ui_root/study-lab.css" \
  "$ui_root/study-lab.js" \
  "$ui_root/vendor/katex/LICENSE" \
  "$ui_root/vendor/katex/README-LATTICE.md" \
  "$ui_root/vendor/katex/katex.min.css" \
  "$ui_root/vendor/katex/katex.min.js" \
  "$ui_root/vendor/katex/fonts/KaTeX_Main-Regular.woff2" \
  "$ui_root/pdf-reader.html" \
  "$ui_root/pdf-reader.css" \
  "$ui_root/pdf-reader.js" \
  "$ui_root/pdf-reader-lifecycle.mjs" \
  "$ui_root/vendor/pdfjs/LICENSE" \
  "$ui_root/vendor/pdfjs/build/pdf.min.mjs" \
  "$ui_root/vendor/pdfjs/build/pdf.worker.min.mjs" \
  "$ui_root/vendor/pdfjs/web/pdf_viewer.mjs" \
  "$ui_root/vendor/pdfjs/web/pdf_viewer.css"; do
  if [[ ! -f "$resource" ]]; then
    print -u2 "Missing app resource: $resource"
    exit 1
  fi
done

/bin/mkdir -p "$staged_app/Contents/MacOS" "$staged_app/Contents/Resources/server"
/bin/cp "$native_root/Info.plist" "$staged_app/Contents/Info.plist"
/bin/cp -R "$ui_root" "$staged_app/Contents/Resources/ui"
/bin/cp "$server_source" "$staged_app/Contents/Resources/server/library_ui.py"
/bin/cp "$vault_source" "$staged_app/Contents/Resources/server/library_vault.py"
/bin/cp "$tutor_source" "$staged_app/Contents/Resources/server/lattice_tutor.py"
/bin/cp "$study_source" "$staged_app/Contents/Resources/server/study_lab.py"
/bin/cp -R "$tutor_vendor_root" "$staged_app/Contents/Resources/server/vendor"
/usr/bin/find "$staged_app/Contents/Resources/server/vendor" -type f -name '*.pyc' -delete
/usr/bin/find "$staged_app/Contents/Resources/server/vendor" -type d -name '__pycache__' -empty -delete
/bin/cp "$storage_source" "$staged_app/Contents/Resources/server/move_library.py"
/bin/cp "$native_root/ImmersiveEPUB.js" "$staged_app/Contents/Resources/ImmersiveEPUB.js"
/bin/cp "$native_root/LibraryWorkspace.js" "$staged_app/Contents/Resources/LibraryWorkspace.js"
/bin/cp "$library_root/THIRD_PARTY_NOTICES.md" "$staged_app/Contents/Resources/THIRD_PARTY_NOTICES.md"

target_arch=$(/usr/bin/uname -m)
/usr/bin/swiftc \
  -O \
  -target "${target_arch}-apple-macosx13.0" \
  -framework AppKit \
  -framework CryptoKit \
  -framework PDFKit \
  -framework Security \
  -framework WebKit \
  -lsqlite3 \
  "$native_root/ReaderModels.swift" \
  "$native_root/LibraryIdentity.swift" \
  "$native_root/ReaderStore.swift" \
  "$native_root/ReaderBridge.swift" \
  "$native_root/MacUpdateChecker.swift" \
  "$native_root/MacUpdateInstaller.swift" \
  "$native_root/CSLibraryApp.swift" \
  "$native_root/ImmersiveReaderCoordinator.swift" \
  "$native_root/NativePDFReaderController.swift" \
  "$native_root/NativePDFReaderUI.swift" \
  "$native_root/NativePDFReaderState.swift" \
  -o "$staged_app/Contents/MacOS/Lattice"

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
  /usr/bin/iconutil -c icns "$iconset" -o "$staged_app/Contents/Resources/AppIcon.icns"
fi

/usr/bin/plutil -lint "$staged_app/Contents/Info.plist" >/dev/null
/usr/bin/codesign --force --deep --sign - "$staged_app" >/dev/null
/usr/bin/codesign --verify --deep --strict "$staged_app"
for bundled in \
  "$staged_app/Contents/MacOS/Lattice" \
  "$staged_app/Contents/Resources/ui/index.html" \
  "$staged_app/Contents/Resources/ui/app.js" \
  "$staged_app/Contents/Resources/ui/tutor.js" \
  "$staged_app/Contents/Resources/ui/tutor-styles.css" \
  "$staged_app/Contents/Resources/ui/study-lab.html" \
  "$staged_app/Contents/Resources/ui/study-lab.css" \
  "$staged_app/Contents/Resources/ui/study-lab.js" \
  "$staged_app/Contents/Resources/ui/vendor/katex/LICENSE" \
  "$staged_app/Contents/Resources/ui/vendor/katex/README-LATTICE.md" \
  "$staged_app/Contents/Resources/ui/vendor/katex/katex.min.css" \
  "$staged_app/Contents/Resources/ui/vendor/katex/katex.min.js" \
  "$staged_app/Contents/Resources/ui/vendor/katex/fonts/KaTeX_Main-Regular.woff2" \
  "$staged_app/Contents/Resources/ui/pdf-reader.html" \
  "$staged_app/Contents/Resources/ui/pdf-reader.js" \
  "$staged_app/Contents/Resources/ui/pdf-reader-lifecycle.mjs" \
  "$staged_app/Contents/Resources/ui/vendor/pdfjs/build/pdf.min.mjs" \
  "$staged_app/Contents/Resources/server/library_ui.py" \
  "$staged_app/Contents/Resources/server/library_vault.py" \
  "$staged_app/Contents/Resources/server/lattice_tutor.py" \
  "$staged_app/Contents/Resources/server/study_lab.py" \
  "$staged_app/Contents/Resources/server/vendor/pypdf/__init__.py" \
  "$staged_app/Contents/Resources/server/vendor/pypdf-LICENSE" \
  "$staged_app/Contents/Resources/server/move_library.py" \
  "$staged_app/Contents/Resources/ImmersiveEPUB.js" \
  "$staged_app/Contents/Resources/LibraryWorkspace.js" \
  "$staged_app/Contents/Resources/THIRD_PARTY_NOTICES.md"; do
  [[ -f "$bundled" ]] || { print -u2 "Staged app is incomplete: $bundled"; exit 1; }
done

if [[ -d "$app_path/Contents" ]]; then
  /bin/mv "$app_path" "$previous_app"
fi
if ! /bin/mv "$staged_app" "$app_path"; then
  [[ -d "$previous_app/Contents" ]] && /bin/mv "$previous_app" "$app_path"
  print -u2 "Could not install the verified app"
  exit 1
fi
/bin/rm -rf "$previous_app"
/usr/bin/touch "$app_path"
print "Built and verified $app_path"
