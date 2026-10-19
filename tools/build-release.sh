#!/bin/bash
# Build only. No installation, loading, security changes or network operations.
set -euo pipefail
ACP_ROOT="$(cd "$(dirname "$0")/.." && pwd -P)"
mkdir -p "$ACP_ROOT/output"
ACP_RUN="$(mktemp -d "$ACP_ROOT/output/release-$(date -u +%Y%m%dT%H%M%SZ)-XXXXXX")"
printf '%s\n' "$ACP_RUN" > "$ACP_ROOT/output/last-run.txt"
exec > >(tee "$ACP_RUN/preparation.log") 2>&1
printf 'AMDMicrophone Release preparation: %s\n' "$ACP_RUN"
printf 'PREFLIGHT\n' > "$ACP_RUN/STATUS.txt"
python3 "$ACP_ROOT/tools/verify_sources.py" "$ACP_RUN/source-manifest.json"

{
    /usr/bin/sw_vers
    /usr/bin/uname -m
    /usr/bin/git --version
    /usr/bin/xcode-select -p
    /usr/bin/xcrun --find clang
    /usr/bin/xcrun clang --version
    /usr/bin/xcrun --sdk macosx --show-sdk-version
} > "$ACP_RUN/available-tools.txt" 2>&1

if ! ACP_XCODEBUILD="$(/usr/bin/xcrun --find xcodebuild 2> "$ACP_RUN/xcodebuild-discovery-error.txt")"; then
    printf 'BLOCKED_NO_FULL_XCODE\n' > "$ACP_RUN/STATUS.txt"
    printf 'Xcode completo non disponibile; nessuna compilazione avviata.\n'
    exit 3
fi
case "$ACP_XCODEBUILD" in
    *.app/Contents/Developer/usr/bin/xcodebuild) ;;
    *) printf 'BLOCKED_UNEXPECTED_XCODE_PATH\n' > "$ACP_RUN/STATUS.txt"; exit 4 ;;
esac
"$ACP_XCODEBUILD" -version > "$ACP_RUN/xcode-version.txt"
ACP_SDK_VERSION="$(/usr/bin/xcrun --sdk macosx --show-sdk-version)"
if [ -n "${ACP_EXPECT_XCODE_BUILD:-}" ]; then
    grep -Fx "Build version $ACP_EXPECT_XCODE_BUILD" "$ACP_RUN/xcode-version.txt"
fi
if [ -n "${ACP_EXPECT_SDK_VERSION:-}" ]; then
    [ "$ACP_SDK_VERSION" = "$ACP_EXPECT_SDK_VERSION" ]
fi

mkdir -p "$ACP_RUN/tmp"
export TMPDIR="$ACP_RUN/tmp/"
ACP_BUILD_ARGS=(
    -project "$ACP_ROOT/upstream/AMDMicrophone.xcodeproj"
    -scheme AMDMicrophone
    -configuration Release
    -arch x86_64
    ONLY_ACTIVE_ARCH=NO
    CODE_SIGNING_ALLOWED=NO
    "SYMROOT=$ACP_RUN/build"
    "OBJROOT=$ACP_RUN/obj"
    "DSTROOT=$ACP_RUN/dst"
    "SHARED_PRECOMPS_DIR=$ACP_RUN/pch"
    "CLANG_MODULE_CACHE_PATH=$ACP_RUN/ModuleCache.noindex"
    -derivedDataPath "$ACP_RUN/DerivedData"
)
printf '%q ' "$ACP_XCODEBUILD" "${ACP_BUILD_ARGS[@]}" build > "$ACP_RUN/build-command.txt"
printf '\n' >> "$ACP_RUN/build-command.txt"
"$ACP_XCODEBUILD" "${ACP_BUILD_ARGS[@]}" -showBuildSettings -json > "$ACP_RUN/build-settings.json" 2> "$ACP_RUN/build-settings-errors.txt"
printf 'BUILDING\n' > "$ACP_RUN/STATUS.txt"
set +e
"$ACP_XCODEBUILD" "${ACP_BUILD_ARGS[@]}" -resultBundlePath "$ACP_RUN/Release.xcresult" build 2>&1 | tee "$ACP_RUN/build.log"
ACP_BUILD_EXIT=${PIPESTATUS[0]}
set -e
printf '%s\n' "$ACP_BUILD_EXIT" > "$ACP_RUN/build-exit-code.txt"
if [ "$ACP_BUILD_EXIT" -ne 0 ]; then
    printf 'BUILD_FAILED\n' > "$ACP_RUN/STATUS.txt"
    exit "$ACP_BUILD_EXIT"
fi
python3 "$ACP_ROOT/tools/verify_sources.py" "$ACP_RUN/source-manifest-after.json"
python3 "$ACP_ROOT/tools/inspect_candidate.py" "$ACP_RUN/build/Release/AMDMicrophone.kext" "$ACP_RUN/inspection"
python3 - "$ACP_RUN" <<'PY'
import datetime, hashlib, json, os, pathlib, sys
root = pathlib.Path(sys.argv[1])
allowed = ['GITHUB_REPOSITORY', 'GITHUB_SHA', 'GITHUB_RUN_ID', 'GITHUB_RUN_ATTEMPT',
           'RUNNER_OS', 'RUNNER_ARCH', 'ImageOS', 'ImageVersion', 'DEVELOPER_DIR']
data = {'utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'context': {k: os.environ[k] for k in allowed if k in os.environ},
        'source_commit': 'c77833e1eef3b22df02f4b1d8f87e15e4e02f0c9',
        'sdk_commit': 'c41d877b64e7fd916bd271390bcdf30f7deb7b7a',
        'code_signing_allowed': False,
        'loaded_or_installed': False}
(root / 'build-provenance.json').write_text(json.dumps(data, indent=2) + '\n')
PY
/usr/bin/ditto -c -k --keepParent "$ACP_RUN/build/Release/AMDMicrophone.kext" "$ACP_RUN/AMDMicrophone-c77833e-Release-x86_64-UNSIGNED.zip"
/usr/bin/shasum -a 256 "$ACP_RUN/AMDMicrophone-c77833e-Release-x86_64-UNSIGNED.zip" > "$ACP_RUN/archive-sha256.txt"
printf 'BUILT_AND_STATICALLY_INSPECTED_NOT_INSTALLED\n' > "$ACP_RUN/STATUS.txt"
printf 'Candidato compilato e ispezionato. Non installato: %s\n' "$ACP_RUN"
