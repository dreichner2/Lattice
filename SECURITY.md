# Security Policy

Lattice is a local desktop application that opens untrusted PDF, EPUB, and
text files. The principal security goal is to keep those files and all reading
data on the selected computer while preventing local content from escaping the
library boundary or executing active web content.

## Supported version

The current release line is version 2.x on macOS 13 or later and Windows 10
build 19041 or later. Security fixes are reviewed and tested on `main` before
they are included in a stable tagged release.

## Reporting a vulnerability

Do not post sensitive details in a public issue. Send the repository owner a
private GitHub message or use a private GitHub security advisory when available.
Include the affected commit, reproduction steps, expected impact, and whether a
malicious document is required.

## Security properties

### Local service

- Binds only to `127.0.0.1`.
- Rejects non-loopback `Host` values.
- Publishes a protocol version and library-root identity.
- Serves only currently indexed files beneath approved payload roots.
- Resolves paths and rejects traversal and symlink escape.
- Requires a random in-memory token for platform file actions, reader-state APIs,
  and Tutor chat/cancel/reset requests.
- Requires a separate unguessable per-launch capability for every Study Lab
  read and mutation. Packaged apps pass it privately to the server and deliver
  it to the owning webview through a URL fragment that is immediately moved to
  tab-scoped session storage; it is never returned by a public API or sent in a
  request URL.
- Requires that token for file import and metadata mutation. Browser requests
  must be same-origin; native clients may omit `Origin` and authenticate with
  the token over loopback.
- Streams imports to a bounded temporary file, validates the supported format,
  computes integrity fields locally, and atomically installs a collision-safe
  payload and adjacent sidecar.
- Exits when its desktop parent disappears when launched by either packaged app.

### Study Lab Python kernel

- Study Lab can execute Python cells through a persistent CPython process
  owned by the local service. This is **trusted execution, not a sandbox**:
  cells run locally with the user's full permissions, exactly like running a
  script in a terminal.
- Kernel reads and requests require the separate per-launch Study capability;
  run and restart requests additionally require the ordinary action token. The
  bridge process does not inherit the private Study capability.
- The bridge permanently separates its private JSON control descriptors from
  notebook standard I/O. Python `sys.stdout`/`sys.stderr` writes are retained
  only up to their caps; direct native-descriptor and subprocess output is
  discarded instead of entering the control channel. Tracebacks, result
  rendering, bridge diagnostics, and PNG encoding are bounded while produced.
- Interactive `input()` is blocked. A timeout, restart, deletion, idle
  eviction, or app shutdown terminates the managed process tree (a kill-on-close
  Job Object on Windows and a dedicated process group on POSIX), invalidates
  in-flight results, and prevents later kernel admission after shutdown. This
  is cleanup containment, not hostile-code isolation: trusted POSIX code can
  deliberately leave its process group, just as it can alter or delete user
  files with the user's permissions.
- The Windows service is packaged as a directory bundle so the process that
  hosts the embedded interpreter is assigned to its Job Object before notebook
  code starts; the packaged Windows test verifies restart kills a child probe.
- One kernel is retained per notebook, with at most eight managed kernel trees
  at once. Notebook deletion/restart and execution admission share a generation
  boundary so a result from an older kernel is never accepted as current.

### Windows installer and updater

- The one-click bootstrap downloads the pinned `v2.4.2` Windows release and
  compares it with its published SHA-256 companion before installation. It does
  not use a mutable GitHub Actions artifact or require a GitHub token.
- Automatic updates are supported only from the per-user versioned installation
  under `%LOCALAPPDATA%\Programs\Lattice\versions\<version>`; portable and
  development copies do not self-update.
- The app fetches fixed `update-manifest.json` and
  `update-manifest.json.sig` assets from the repository's latest stable GitHub
  release. It verifies the exact manifest bytes with its embedded RSA-3072
  public key using SHA-256 and PKCS#1 v1.5 before parsing or trusting any
  manifest field.
- Only strictly newer stable `major.minor.patch` versions are accepted. The
  signed repository, `v<version>` tag, exact versioned HTTPS GitHub asset URL,
  size, and SHA-256 must all agree.
- Downloads, manifests, signatures, archive entry counts, and extracted bytes
  are bounded. ZIP traversal, duplicate paths, symlinks, reparse points, and
  incomplete or mismatched package metadata are rejected.
- An update is extracted beside the active version. The candidate must start
  from that exact version directory, own an isolated loopback server, pass its
  `/api/health` response, and prove that the complete shared interface has
  initialized before it may replace `active-version.json` and the Start-menu
  shortcut. Each replacement is atomic; the active-version authority is
  published first so an old shortcut launch redirects to it.
- Candidate promotion takes a cross-process lock and re-reads the active
  authority at commit time. An older candidate that finishes after a newer one
  cannot roll the installation back, and stale cleanup never prunes a newer
  staged or active version.
- Only after promotion succeeds does the candidate ask the superseded window
  to close. Current handoffs bind that request to the recorded launcher PID
  and exact previous-version executable path; the 2.0.1 compatibility path
  still requires an exact canonical executable-path match.
- A desktop launcher mirror is eligible for replacement only when its SHA-256
  exactly matches the superseded installed executable and it is a regular
  `.exe` outside the installation root. The detached helper binds the old
  process by PID, start time, and executable path, rechecks the target digest
  after that process exits, copies and verifies the healthy candidate, and uses
  an atomic replacement with rollback backup. A changed or unrelated file is
  left untouched.
- The healthy active version is never overwritten in place. After successful
  promotion, the active version and one previous healthy version are retained;
  recognized older non-running versions may be pruned. Launching a stale older
  executable redirects to the recorded active version.

The updater's release-manifest signature is not Windows Authenticode. The
current Windows executable is not Authenticode-signed, so Microsoft Defender
SmartScreen or Smart App Control may warn or block it based on local policy and
reputation. Users must not be told to disable or bypass Windows protections to
install Lattice.

### macOS updater

- Direct installation is enabled only when the running bundle is exactly
  `/Applications/Lattice.app` and its parent directory is writable. Repository
  builds and copies at other paths never replace themselves.
- The app downloads the same fixed `update-manifest.json` and signature used by
  Windows, verifies the RSA-3072 signature before parsing it, and accepts only
  a strictly newer stable release with an exact version-pinned
  `macos-arm64` GitHub URL, signed size, and SHA-256.
- Downloads are staged under the current user's Application Support directory.
  The extracted archive must contain exactly one `Lattice.app`; symbolic links,
  special files, excessive file counts or bytes, the wrong bundle identifier or
  version, a non-arm64 executable, and invalid code-signature structure are
  rejected.
- A helper mode in the already-running executable waits for the old process to
  exit, then re-verifies the signed manifest and archive before replacement.
  The existing bundle is moved to a collision-safe transient backup rather than
  deleted before the candidate is known healthy.
- The candidate must launch from the installed path and write an
  operation-token and PID-bound health marker only after the loopback service
  and shared shelf load. Tokens stay in mode-0600 operation records and are
  never placed in helper or candidate process arguments. An early exit or
  90-second timeout terminates the candidate, restores the previous bundle,
  discards the failed candidate, and relaunches it. A healthy candidate deletes
  the transient backup, so successful updates retain no older app bundle.
- The macOS archive is currently ad-hoc signed. That signature proves bundle
  consistency, not Developer ID identity; release authorization comes from the
  separately verified manifest signature and archive digest. The updater never
  modifies the selected library, Syncthing configuration, or reader database.

### Storage relocation

- Move Library requires the current Syncthing folder to match the exact stable
  Lattice folder ID and source path and to be up to date before it pauses or
  copies anything.
- Syncthing discovery reads the current user's configuration only to obtain its
  GUI address and API key. The key remains in memory, is never logged, passed on
  a command line, stored in the library, or sent anywhere except an explicitly
  validated loopback HTTP endpoint. TLS and non-loopback GUI endpoints are
  refused instead of bypassing certificate or network trust; proxy use and HTTP
  redirects are disabled for these authenticated API calls.
- Source roots, destination ancestry, free capacity, file types, and reparse or
  symbolic links are validated before copying. Every regular file is written to
  an operation-owned staging directory, flushed, and compared to its destination
  using SHA-256 before the destination becomes active.
- The same Syncthing folder record is paused and repointed; no replacement
  folder ID is created. The original directory is deleted only after the new
  path is retained, Syncthing needs no restart, and its resumed scan is healthy.
  Failures attempt to restore the original path and pause state and never
  authorize deletion of the original library. If the API is unavailable during
  rollback, both copies are retained and the unconfirmed state is reported.
- macOS refuses relocation while `Lattice.app` is inside the selected library;
  Windows passes its installed application directory as an equivalent protected
  path. This prevents the helper from deleting its own running application.
- Windows drive eject saves reconnect state and starts a strict eject-helper
  mode only from an executable and working directory outside the library
  volume. Before disposal, Lattice snapshots the local service process tree,
  every process reported by its WebView2 environment, and the browser process.
  The helper binds every wait to both PID and process start time, then asks
  Configuration Manager to resolve the saved USB device ID only after the main
  app and every captured child process have exited.
- The eject helper uses only `CM_Request_Device_EjectW`; it never locks,
  dismounts, offlines, or rewrites a volume mount point. After a two-second
  handle drain, at most eight short attempts are allowed and only for
  Configuration Manager pending-close or outstanding-open vetoes. A safe-to-unplug claim
  requires `CR_SUCCESS`; otherwise the exact final veto is shown, a local
  diagnostic is retained, and the disconnected reconnect record remains
  intact.

### Release signing key custody and rotation

The update-manifest private key is release authority. It must stay local,
permission-restricted, backed up securely, and outside the repository, release
assets, GitHub secrets, and CI workflows. The application contains only the
public key. `scripts/sign_update_manifest.py` refuses a private key unless its
public DER SHA-256 matches the checked-in production fingerprint
`d83bee18c8410be46d7dccac3784ec0ecc1fdd516fa5b27b0de1fe15580348bf`, and it
does not print private-key content or provider diagnostics.

Release operators build and sign exact artifacts with the checked-in helpers:

```bash
python3 scripts/build_update_manifest.py \
  --version X.Y.Z \
  --archive artifacts/Lattice-Windows-win-x64.zip \
  --macos-archive artifacts/Lattice-macOS.zip \
  --published-at YYYY-MM-DDTHH:MM:SSZ \
  --output update-manifest.json

python3 scripts/sign_update_manifest.py \
  --manifest update-manifest.json \
  --private-key /secure/off-repository/lattice-release-private.pem \
  --output update-manifest.json.sig
```

A planned signing-key rotation must first ship a reviewed client update that
trusts the replacement public key, using a build and manifest still authorized
by the current key. Only after that trusted transition build is available may
new manifests be signed with the replacement key. If the current private key is
lost or suspected compromised, freeze automatic releases and establish the new
trust root through a separately authenticated manual distribution; do not use a
possibly compromised key to authorize its own replacement.

### EPUB isolation

- Book resources are served with a restrictive content security policy.
- Book-supplied JavaScript is disabled.
- External connections, forms, objects, and child frames are disabled.
- Archive traversal, encrypted entries, duplicate paths, excessive resource
  counts, excessive uncompressed size, and suspicious compression ratios are
  rejected.
- Only resources from the validated EPUB package are served.

### Native files

- Native file resolution accepts only relative paths under the `books/`,
  `papers/`, and `lectures/` payload roots.
- Paths are canonicalized and symlinks are resolved before containment checks.
- Only PDF, EPUB, and TXT files are accepted by the reader/import workflow.

### Imported metadata and Codex

- Sidecar names append `.library.json` to the full payload filename; clients do
  not supply an arbitrary destination path.
- `path`, `bytes`, `sha256`, material type, access defaults, and import
  provenance are computed and owned by the local server. Model output and
  manual edits cannot replace them.
- Sidecars are parsed as untrusted, size-bounded JSON. Unknown subject IDs and
  malformed fields fall back to the checked-in taxonomy instead of changing the
  server's trust boundary.
- Optional enrichment invokes the authenticated local Codex CLI with
  `gpt-5.6-luna` in an ephemeral temporary read-only context with execution,
  browser, app, image, and workspace tools disabled. Lattice does not read,
  copy, print, or synchronize Codex credential files.
- The Codex executable must resolve from an absolute install or `PATH`
  directory outside the selected library. Relative entries, the current
  directory, library-owned executables, and symlinks into the synchronized
  library are rejected before any subprocess is launched.
- The model prompt contains the filename, selected material kind, extracted
  EPUB publication metadata, and allowed subject list—not the document bytes or
  full text. PDF requests are filename-only. Supplied fields are treated as
  untrusted strings, and structured output is validated before it can update
  descriptive fields.
- Missing CLI, signed-out state, timeout, model error, or invalid output never
  prevents the already validated local import from completing.

### Lattice Tutor and Codex

- Tutor is closed and inactive by default. It invokes Codex only after the user
  sends a question; ordinary shelf, reader, notebook, import, and video use does
  not send source text to a model.
- It reuses the authenticated local Codex session. Lattice never reads, copies,
  prints, synchronizes, or places credential contents in prompts or arguments.
- Requests identify catalog work/course IDs, not paths. The server resolves
  those IDs against a fresh library snapshot, limits selection and message
  sizes, and rejects unknown or restricted works.
- Eligible file and library-document paths must resolve to regular files inside
  the selected library. Lattice repeats canonical containment immediately
  before indexing and prompt construction so a swapped or cataloged external
  symlink is excluded.
- Every Codex turn is ephemeral and ignores user configuration and repository
  instruction files. Apps, plugins, browser, computer-use, image, skill,
  workspace-dependency, memory, hook, and multi-agent capabilities are disabled.
  Hosted web search and model-tool network access are disabled.
- The child process receives an allowlisted environment without API keys or
  proxy credentials. On every platform, Lattice writes only the bounded,
  scope-filtered turn context to one disposable workspace under the system
  temporary directory, uses Codex's standard read-only sandbox, and disables
  shell, unified-exec, and code-mode access. The original library, including
  external-drive sources, unrelated sidecars, credential storage, restricted
  editions, and the private Tutor index remain outside the Tutor turn.
- PDFs, EPUBs, supported source archives, and plain text are extracted under
  bounded file, member, and text limits. The private SQLite/FTS cache is created
  outside the synchronized library with user-only directory/file modes where
  the platform supports them. A source removed from eligibility is pruned, and
  an in-flight stale indexing result is discarded.
- Publisher-marked human-study-only works and personalized/private editions are
  excluded from whole-library and selected modes. This is an access-policy
  boundary in addition to a filesystem sandbox boundary.
- Library text and retrieved excerpts are treated as untrusted data, never as
  instructions. Structured model output is size-bounded, and citations are
  accepted only when their source key was actually staged as an excerpt or
  course-metadata block for that turn.
- Conversation history is bounded, memory-only, expires after inactivity, and
  is removed on reset or service exit. It is not written to the library,
  Syncthing, reader database, or Tutor source index.
- A Tutor request sends the user's question, bounded conversation history,
  source manifest, relevant eligible excerpts, and selected video catalog
  metadata to OpenAI through Codex. Video frames, audio, captions, and
  transcripts are not available unless separately present as an eligible local
  source, so the prompt forbids claims of having watched a lecture.

### Study Lab

- Notebook storage uses a private per-library namespace outside the synchronized
  library and rejects linked, reparse-point, in-library, and home-directory
  fallback locations that would weaken its owner-only boundary.
- Every Study endpoint requires the server's per-launch private capability;
  writes additionally require the ordinary action token and fresh
  compare-and-swap revision.
- Packaged desktop clients own an isolated server process and bind native bridge
  messages and top-level navigation to that server's exact scheme, host, and
  effective port, rather than trusting every loopback service.
- LaTeX renders from the vendored KaTeX distribution with trust disabled.
  Python cells execute only after an explicit Run action and remain inert when
  rendered. Output text is inserted as text, and plots accept only bounded PNG
  data. Execution has the user's full local permissions and is not a sandbox.

### Device vault

- Vault state is namespaced by the stable Syncthing folder identity and stored
  outside the synchronized library with private directory/file modes where
  supported. A malformed, foreign, oversized, linked, or invalid journal fails
  closed and is never interpreted as permission to prune copies.
- Only curated payload paths backed by durable tracked metadata are eligible.
  Relative paths reject traversal, hidden components, control characters, and
  cross-platform Syncthing glob metacharacters. Copies are named from full
  path and payload SHA-256 values so equal bytes at different paths never share
  destructive lifecycle state.
- Payload paths preserve lexical identity and reject symbolic links, junctions,
  and other Windows reparse points in the payload or any existing parent.
  Verification, journal identity, exact ignores, and deletion therefore refer
  to the same non-linked synchronized path.
- Check out, release, and restore verify SHA-256 at each authority transition.
  Release re-verifies the current local payload, preserves its metadata sidecar,
  journals first, installs the rooted ignore before every broader pattern, and
  then removes only the payload. Restore uses exclusive creation and refuses to
  overwrite a conflicting local file.
- A live managed Syncthing folder must be healthy and Up to Date and is paused
  around release/restore, then resumed and rescanned. A pre-existing exact
  ignore is preserved; only a Lattice-owned marker is removed on restore.
- Reconciliation prunes only unreferenced files matching Lattice's managed
  copy-name format. A surviving `return-pending` payload must still match its
  recorded digest before the ignore is removed or the entry becomes local;
  corrupt state and unknown files are preserved for recovery.

### Reader data

- Native Mac progress, notes, bookmarks, annotations, and sessions are stored
  in its local SQLite database. Windows web-reader state uses a separate local
  SQLite database scoped by library identity.
- Database writes use transactions and WAL mode.
- Daily local backups are retained.
- Reader data can be exported to JSON or Markdown.
- No telemetry, cloud synchronization, or remote annotation service is present.
  Syncthing payload/sidecar replication and optional Codex enrichment are
  separate, explicit boundaries; neither includes live reader databases.

## Remaining trust boundaries

- PDF parsing and rendering depend on Apple's PDFKit on macOS and the installed
  Microsoft Edge WebView2 Runtime on Windows.
- Web rendering depends on WebKit on macOS and WebView2 on Windows.
- The Mac local service depends on the user's Python 3 runtime; the Windows
  artifact bundles its Python service with PyInstaller.
- Optional metadata enrichment and Lattice Tutor depend on the locally installed
  Codex CLI, its authenticated session, selected model availability, and OpenAI
  service connectivity.
- Ad-hoc signing verifies bundle consistency but is not Developer ID
  notarization.
- Desktop update-manifest signing verifies release authorization inside
  Lattice but is neither Windows Authenticode nor Apple Developer ID signing
  and does not create platform reputation.
- Imported books may have restrictive copyright or machine-processing terms;
  access rights are tracked separately from software security.

## Secure-development expectations

Changes that affect path handling, EPUB parsing, native bridge messages,
database migrations, uploads, sidecars, Codex invocation, server lifecycle,
installer behavior, updater trust, release manifests, or key rotation require
tests. Do not weaken content security policy, host validation, catalog
allowlisting, upload limits, archive limits, taxonomy validation, native path
containment, signed-manifest validation, candidate health gates, or rollback
retention to support a single malformed document or release.
