#!/bin/sh
set -eu

case "$0" in
  /*) SCRIPT_PATH=$0 ;;
  *) SCRIPT_PATH=$PWD/$0 ;;
esac
SCRIPT_DIR=${SCRIPT_PATH%/*}
SCRIPT_DIR=$(CDPATH= cd -- "$SCRIPT_DIR" && pwd)
cd "$SCRIPT_DIR"

OS_NAME=$(uname -s 2>/dev/null || printf unknown)
case "$OS_NAME" in
  Linux) NODE_PLATFORM=linux ;;
  Darwin) NODE_PLATFORM=darwin ;;
  *) printf '%s\n' "[ERROR] Unsupported operating system: $OS_NAME" >&2; exit 1 ;;
esac

if [ -n "${ZZ_RUNTIME_DIR:-}" ]; then
  RUNTIME_DIR=$ZZ_RUNTIME_DIR
elif [ -n "${XDG_CACHE_HOME:-}" ]; then
  RUNTIME_DIR="$XDG_CACHE_HOME/zenonzard/runtime"
elif [ -n "${HOME:-}" ]; then
  case "$OS_NAME" in
    Linux) RUNTIME_DIR="$HOME/.cache/zenonzard/runtime" ;;
    Darwin) RUNTIME_DIR="$HOME/Library/Caches/zenonzard/runtime" ;;
  esac
else
  RUNTIME_DIR="$SCRIPT_DIR/.zz-runtime"
fi
BOOTSTRAP_LOG="$RUNTIME_DIR/bootstrap.log"
NODE_VERSION=v22.23.1
MIN_NODE_MAJOR=20
LAUNCHER_VERSION=2026.08.01.5
CURRENT_STAGE=initializing
mkdir -p "$RUNTIME_DIR"
: > "$BOOTSTRAP_LOG"

log() {
  printf '%s\n' "$*"
  printf '%s\n' "$*" >> "$BOOTSTRAP_LOG"
}

fail() {
  log "[ERROR] $*"
  exit 1
}

run_with_heartbeat() {
  label=$1
  shift
  "$@" &
  command_pid=$!
  elapsed=0
  while kill -0 "$command_pid" 2>/dev/null; do
    sleep 15
    if kill -0 "$command_pid" 2>/dev/null; then
      elapsed=$((elapsed + 15))
      log "$label is still running (${elapsed}s elapsed)."
    fi
  done
  wait "$command_pid"
}

on_exit() {
  status=$?
  if [ "$status" -ne 0 ]; then
    log "[ERROR] Bootstrap failed during: $CURRENT_STAGE"
    log "[ERROR] Diagnostic log: $BOOTSTRAP_LOG"
  fi
}
trap on_exit EXIT HUP INT TERM

if [ ! -f package.json ]; then
  fail "package.json was not found next to this launcher."
fi
if [ ! -f requirements-runtime.txt ]; then
  fail "requirements-runtime.txt was not found next to this launcher."
fi

MACHINE=$(uname -m 2>/dev/null || printf unknown)
case "$MACHINE" in
  x86_64|amd64) NODE_ARCH=x64 ;;
  arm64|aarch64) NODE_ARCH=arm64 ;;
  *) fail "Unsupported CPU architecture: $MACHINE" ;;
esac

command_exists() {
  command -v "$1" >/dev/null 2>&1
}

python_is_supported() {
  "$1" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1
}

node_is_supported() {
  command_exists node || return 1
  command_exists npm || return 1
  node -e "process.exit(Number(process.versions.node.split('.')[0]) >= $MIN_NODE_MAJOR ? 0 : 1)" >/dev/null 2>&1
}

detect_package_manager() {
  if command_exists apt-get; then
    PACKAGE_MANAGER=apt
  elif command_exists dnf; then
    PACKAGE_MANAGER=dnf
  elif command_exists pacman; then
    PACKAGE_MANAGER=pacman
  elif command_exists zypper; then
    PACKAGE_MANAGER=zypper
  else
    PACKAGE_MANAGER=none
  fi
}

run_as_root() {
  if [ "$(id -u)" -eq 0 ]; then
    "$@"
  elif command_exists sudo; then
    log "Administrator access is required once to install missing system packages."
    sudo "$@"
  elif command_exists pkexec; then
    log "Administrator access is required once to install missing system packages."
    pkexec "$@"
  else
    fail "Missing system packages require root access, but neither sudo nor pkexec is available."
  fi
}

install_base_packages() {
  detect_package_manager
  CURRENT_STAGE="installing base Linux packages"
  case "$PACKAGE_MANAGER" in
    apt)
      run_as_root apt-get update
      run_as_root apt-get install -y python3 python3-venv python3-pip ca-certificates curl xz-utils coreutils
      ;;
    dnf)
      run_as_root dnf install -y python3 python3-pip ca-certificates curl xz coreutils
      ;;
    pacman)
      run_as_root pacman -Sy --needed --noconfirm python python-pip ca-certificates curl xz coreutils
      ;;
    zypper)
      run_as_root zypper --non-interactive install python3 python3-pip ca-certificates curl xz coreutils
      ;;
    *)
      fail "No supported package manager was found. Supported Linux managers: apt, dnf, pacman, zypper."
      ;;
  esac
}

install_electron_packages() {
  detect_package_manager
  CURRENT_STAGE="installing Electron Linux libraries"
  case "$PACKAGE_MANAGER" in
    apt)
      run_as_root apt-get update
      run_as_root apt-get install -y libasound2 libatk-bridge2.0-0 libatk1.0-0 libcairo2 libcups2 libdrm2 libgbm1 libgtk-3-0 libnspr4 libnss3 libpango-1.0-0 libx11-6 libx11-xcb1 libxcb1 libxcomposite1 libxdamage1 libxext6 libxfixes3 libxkbcommon0 libxrandr2 libxss1
      ;;
    dnf)
      run_as_root dnf install -y alsa-lib atk at-spi2-atk cairo cups-libs gtk3 libdrm libX11 libXcomposite libXdamage libXext libXfixes libXrandr libXScrnSaver libxkbcommon mesa-libgbm nspr nss pango
      ;;
    pacman)
      run_as_root pacman -Sy --needed --noconfirm alsa-lib at-spi2-core cairo cups gtk3 libdrm libx11 libxcomposite libxdamage libxext libxfixes libxkbcommon libxrandr libxss mesa nspr nss pango
      ;;
    zypper)
      run_as_root zypper --non-interactive install alsa gtk3 libdrm2 libgbm1 libX11-6 libXcomposite1 libXdamage1 libXext6 libXfixes3 libXrandr2 libXss1 libxkbcommon0 mozilla-nspr mozilla-nss pango
      ;;
    *)
      fail "Electron is missing shared libraries and no supported package manager was found."
      ;;
  esac
}

ensure_electron_extractor() {
  if [ "$OS_NAME" = Darwin ]; then
    command_exists ditto || fail "macOS ditto is required to extract Electron."
    return
  fi
  command_exists unzip && return
  detect_package_manager
  CURRENT_STAGE="installing ZIP extractor"
  case "$PACKAGE_MANAGER" in
    apt)
      run_as_root apt-get update
      run_as_root apt-get install -y unzip
      ;;
    dnf) run_as_root dnf install -y unzip ;;
    pacman) run_as_root pacman -Sy --needed --noconfirm unzip ;;
    zypper) run_as_root zypper --non-interactive install unzip ;;
    *) fail "Electron extraction requires unzip, but no supported package manager was found." ;;
  esac
}

download_file() {
  url=$1
  destination=$2
  if command_exists curl; then
    curl --fail --location --retry 3 --connect-timeout 20 --output "$destination" "$url"
  elif command_exists wget; then
    wget --tries=3 --timeout=20 --output-document="$destination" "$url"
  else
    fail "Neither curl nor wget is available."
  fi
}

sha256_file() {
  if command_exists sha256sum; then
    sha256sum "$1" | awk '{print $1}'
  elif command_exists shasum; then
    shasum -a 256 "$1" | awk '{print $1}'
  else
    fail "No SHA-256 utility is available."
  fi
}

ensure_bootstrap_tools() {
  missing=0
  command_exists tar || missing=1
  command_exists awk || missing=1
  command_exists curl || command_exists wget || missing=1
  command_exists sha256sum || command_exists shasum || missing=1
  if [ "$missing" -ne 0 ]; then
    if [ "$OS_NAME" = Linux ]; then
      install_base_packages
    else
      fail "tar, awk, a downloader, and a SHA-256 utility are required to bootstrap on macOS."
    fi
  fi
}

ensure_node() {
  CURRENT_STAGE="checking Node.js"
  if node_is_supported; then
    log "Using Node.js $(node --version) from $(command -v node)."
    return
  fi

  ensure_bootstrap_tools
  archive_name="node-$NODE_VERSION-$NODE_PLATFORM-$NODE_ARCH"
  if [ "$NODE_PLATFORM" = linux ]; then
    archive_file="$archive_name.tar.xz"
  else
    archive_file="$archive_name.tar.gz"
  fi
  node_home="$RUNTIME_DIR/$archive_name"
  node_archive="$RUNTIME_DIR/$archive_file"
  checksums="$RUNTIME_DIR/node-$NODE_VERSION-SHASUMS256.txt"
  base_url="https://nodejs.org/dist/$NODE_VERSION"

  if [ ! -x "$node_home/bin/node" ]; then
    CURRENT_STAGE="downloading Node.js $NODE_VERSION"
    log "A supported Node.js was not found. Installing a private runtime in $RUNTIME_DIR."
    download_file "$base_url/$archive_file" "$node_archive.partial"
    download_file "$base_url/SHASUMS256.txt" "$checksums.partial"
    expected=$(awk -v name="$archive_file" '$2 == name {print $1}' "$checksums.partial")
    [ -n "$expected" ] || fail "Node.js checksum manifest did not contain $archive_file."
    actual=$(sha256_file "$node_archive.partial")
    [ "$actual" = "$expected" ] || fail "Node.js archive checksum mismatch."
    mv "$node_archive.partial" "$node_archive"
    mv "$checksums.partial" "$checksums"
    tar -xf "$node_archive" -C "$RUNTIME_DIR"
  fi

  PATH="$node_home/bin:$PATH"
  export PATH
  node_is_supported || fail "The private Node.js runtime did not start correctly."
  log "Using private Node.js $(node --version)."
}

select_system_python() {
  if [ -n "${ZZ_PYTHON:-}" ] && python_is_supported "$ZZ_PYTHON"; then
    SYSTEM_PYTHON=$ZZ_PYTHON
  elif command_exists python3 && python_is_supported "$(command -v python3)"; then
    SYSTEM_PYTHON=$(command -v python3)
  elif command_exists python && python_is_supported "$(command -v python)"; then
    SYSTEM_PYTHON=$(command -v python)
  else
    SYSTEM_PYTHON=
  fi
}

ensure_python() {
  CURRENT_STAGE="checking Python"
  select_system_python
  if [ -z "$SYSTEM_PYTHON" ]; then
    [ "$OS_NAME" = Linux ] || fail "Python 3.10 or newer is required on macOS."
    install_base_packages
    select_system_python
  fi
  [ -n "$SYSTEM_PYTHON" ] || fail "Python 3.10 or newer could not be installed."

  python_tag=$($SYSTEM_PYTHON -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
  venv_dir="$RUNTIME_DIR/python-$python_tag-game"
  if [ ! -x "$venv_dir/bin/python" ]; then
    CURRENT_STAGE="creating Python virtual environment"
    if ! "$SYSTEM_PYTHON" -m venv "$venv_dir"; then
      [ "$OS_NAME" = Linux ] || fail "Python venv creation failed."
      install_base_packages
      "$SYSTEM_PYTHON" -m venv "$venv_dir"
    fi
  fi

  ZZ_PYTHON="$venv_dir/bin/python"
  export ZZ_PYTHON PYTHONIOENCODING=utf-8
  python_is_supported "$ZZ_PYTHON" || fail "The private Python runtime is invalid."
  log "Using private Python $($ZZ_PYTHON --version 2>&1)."
}

python_runtime_is_ready() {
  "$ZZ_PYTHON" -c 'import importlib.metadata as m
def pair(name):
    parts=[]
    for chunk in m.version(name).split(".")[:2]:
        digits="".join(c for c in chunk if c.isdigit())
        parts.append(int(digits or 0))
    return tuple((parts + [0, 0])[:2])
import numpy, websockets
valid = pair("numpy") >= (1, 26) and pair("websockets") >= (16, 0)
raise SystemExit(0 if valid else 1)' >/dev/null 2>&1
}

ensure_python_dependencies() {
  CURRENT_STAGE="checking Python dependencies"
  if python_runtime_is_ready; then
    log "Python runtime dependencies are ready."
    return
  fi
  CURRENT_STAGE="installing Python dependencies"
  log "Installing private Python runtime dependencies. This may take several minutes on the first run."
  "$ZZ_PYTHON" -m pip install --upgrade pip
  "$ZZ_PYTHON" -m pip install --requirement requirements-runtime.txt
  python_runtime_is_ready || fail "Python dependencies were installed but failed the runtime import/version check."
}

ensure_node_dependencies() {
  CURRENT_STAGE="checking Electron dependencies"
  if [ ! -f node_modules/electron/cli.js ]; then
    CURRENT_STAGE="installing Electron dependencies"
    log "Installing private Electron dependencies. This may take several minutes on the first run."
    export ELECTRON_SKIP_BINARY_DOWNLOAD=1
    if [ -f package-lock.json ]; then
      run_with_heartbeat "npm dependency installation" npm ci --no-audit --no-fund
    else
      run_with_heartbeat "npm dependency installation" npm install --no-audit --no-fund
    fi
  fi
  [ -f node_modules/electron/cli.js ] || fail "Electron dependencies were not installed correctly."
  ensure_electron_binary
}

electron_archive_is_valid() {
  ARCHIVE_PATH=$1 ARCHIVE_NAME=$2 node - <<'NODE'
const crypto = require('crypto');
const fs = require('fs');
const checksums = require('./node_modules/electron/checksums.json');
const expected = checksums[process.env.ARCHIVE_NAME];
if (!expected) {
  console.error(`Missing packaged checksum for ${process.env.ARCHIVE_NAME}`);
  process.exit(1);
}
const actual = crypto.createHash('sha256').update(fs.readFileSync(process.env.ARCHIVE_PATH)).digest('hex');
if (actual !== expected) {
  console.error(`Electron archive checksum mismatch: expected ${expected}, got ${actual}`);
  process.exit(1);
}
console.log(`Electron archive checksum verified: ${actual}`);
NODE
}

ensure_electron_binary() {
  electron_root="$SCRIPT_DIR/node_modules/electron"
  case "$OS_NAME" in
    Linux) electron_platform_path=electron ;;
    Darwin) electron_platform_path="Electron.app/Contents/MacOS/Electron" ;;
  esac
  electron_version=$(node -p "require('./node_modules/electron/package.json').version")
  electron_dist="$RUNTIME_DIR/electron/$electron_version/$NODE_PLATFORM-$NODE_ARCH"
  electron_bin="$electron_dist/$electron_platform_path"
  ELECTRON_OVERRIDE_DIST_PATH=$electron_dist
  export ELECTRON_OVERRIDE_DIST_PATH
  printf '%s' "$electron_platform_path" > "$electron_root/path.txt"
  if [ -f "$electron_bin" ]; then
    chmod 755 "$electron_bin"
    [ -x "$electron_bin" ] || fail "Cached Electron exists but cannot execute: $electron_bin. Check whether the user cache is on a noexec filesystem."
    log "Using shared Electron runtime: $electron_bin"
    return
  fi

  CURRENT_STAGE="downloading Electron binary"
  archive_name="electron-v${electron_version}-${NODE_PLATFORM}-${NODE_ARCH}.zip"
  download_dir="$RUNTIME_DIR/downloads"
  archive_path="$download_dir/$archive_name"
  partial_path="$archive_path.part"
  official_url="https://github.com/electron/electron/releases/download/v${electron_version}/${archive_name}"
  mirror_base=${ELECTRON_MIRROR:-https://npmmirror.com/mirrors/electron/}
  mirror_base=${mirror_base%/}
  mirror_url="${mirror_base}/${electron_version}/${archive_name}"
  mkdir -p "$download_dir"

  if [ -f "$archive_path" ] && ! electron_archive_is_valid "$archive_path" "$archive_name"; then
    log "Cached Electron archive is invalid. Removing this launcher-owned cache entry and downloading a clean copy."
    rm -f "$archive_path" "$partial_path"
  fi

  if [ ! -f "$archive_path" ]; then
    log "Downloading Electron ${electron_version}. curl will show percentage, speed and ETA below."
    log "Source: $official_url"
    if ! curl --fail --location --retry 2 --connect-timeout 20 --continue-at - --output "$partial_path" "$official_url"; then
      log "The official Electron download failed. Continuing through the Electron mirror."
      log "Source: $mirror_url"
      curl --fail --location --retry 2 --connect-timeout 20 --continue-at - --output "$partial_path" "$mirror_url"
    fi
    mv "$partial_path" "$archive_path"
  else
    log "Using cached Electron archive: $archive_path"
  fi

  CURRENT_STAGE="verifying Electron binary"
  if ! electron_archive_is_valid "$archive_path" "$archive_name"; then
    log "The downloaded archive failed verification. Retrying the mirror once from byte zero."
    rm -f "$archive_path" "$partial_path"
    curl --fail --location --retry 2 --connect-timeout 20 --continue-at - --output "$partial_path" "$mirror_url"
    mv "$partial_path" "$archive_path"
    electron_archive_is_valid "$archive_path" "$archive_name" || {
      rm -f "$archive_path" "$partial_path"
      fail "Electron archive verification failed after a clean mirror retry."
    }
  fi

  CURRENT_STAGE="extracting Electron binary"
  ensure_electron_extractor
  case "$electron_dist" in
    "$RUNTIME_DIR"/electron/*) ;;
    *) fail "Refusing to replace unexpected Electron destination: $electron_dist" ;;
  esac
  rm -rf "$electron_dist"
  mkdir -p "$electron_dist"
  if [ "$OS_NAME" = Linux ]; then
    unzip -q -o "$archive_path" -d "$electron_dist"
  else
    ditto -x -k "$archive_path" "$electron_dist"
  fi
  [ -f "$electron_bin" ] || fail "Electron archive extracted, but the executable file is missing: $electron_bin"
  chmod 755 "$electron_bin"
  [ -x "$electron_bin" ] || fail "Electron exists but is not executable after chmod: $electron_bin. Check whether the user cache is on a noexec filesystem."
  log "Electron executable permissions repaired."
  log "Electron binary installation complete."
}

ensure_electron_libraries() {
  [ "$OS_NAME" = Linux ] || return
  command_exists ldd || fail "ldd is required to validate Electron on Linux."
  electron_bin="$ELECTRON_OVERRIDE_DIST_PATH/electron"
  [ -x "$electron_bin" ] || fail "Electron binary is missing after npm installation."
  ldd_report="$RUNTIME_DIR/electron-ldd.txt"
  ldd "$electron_bin" > "$ldd_report" 2>&1 || true
  missing=$(awk '/not found/ {print $1}' "$ldd_report")
  if [ -n "$missing" ]; then
    log "Electron is missing shared libraries: $missing"
    install_electron_packages
    ldd "$electron_bin" > "$ldd_report" 2>&1 || true
    missing=$(awk '/not found/ {print $1}' "$ldd_report")
    [ -z "$missing" ] || fail "Electron still has missing shared libraries after installation: $missing"
  fi
  log "Electron shared-library check passed."
}

CURRENT_STAGE="bootstrapping runtime"
log "ZENONZARD Linux/macOS launcher"
log "Launcher build: $LAUNCHER_VERSION"
log "Project: $SCRIPT_DIR"
log "Platform: $OS_NAME $MACHINE"
ensure_node
ensure_python
ensure_python_dependencies
ensure_node_dependencies
ensure_electron_libraries

CURRENT_STAGE="complete"
log "Bootstrap complete."
log "Node.js: $(node --version)"
log "npm: $(npm --version)"
log "Python: $($ZZ_PYTHON --version 2>&1)"

if [ "${1:-}" = "--check" ]; then
  log "Launcher check passed."
  trap - EXIT HUP INT TERM
  exit 0
fi

log "Starting ZENONZARD Offline Project."
trap - EXIT HUP INT TERM
exec node node_modules/electron/cli.js .
