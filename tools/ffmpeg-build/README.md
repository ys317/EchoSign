# Portable audio FFmpeg for HDUSign

This recipe builds FFmpeg **8.1.2** from its signed official source release, using
only internal audio codecs and Windows **Schannel**. GPL, nonfree, version-3-only
components, external codec libraries and external TLS libraries are disabled.
The resulting separate command-line executable uses FFmpeg's LGPL 2.1-or-later
license. Windows system DLLs are not redistributed. MinGW runtime notices and
the GCC Runtime Library Exception notices are collected from the build tools.

The source archive was downloaded from `https://ffmpeg.org/releases/` and its
detached signature was verified against FFmpeg release-key fingerprint
`FCF986EA15E6E293A5644F10B4322F04D67658D8`. All three downloaded files have pinned
SHA256 values in `source-lock.json`; builds check the hashes and signature again.

## Build and outputs

The **Build portable audio FFmpeg** GitHub Actions workflow runs manually or on
the dedicated `codex/ffmpeg-audio-build` branch and builds on an
isolated `windows-2022` runner with MSYS2 MINGW64. It has read-only repository
permission and uploads a build artifact; it does not create a software release.
The action implementations are pinned by commit. The rolling MSYS2 package
versions, compiler versions, complete configure arguments, generated config and
build logs are recorded in the corresponding source archive. This records a
rebuildable recipe; it does not claim byte-identical compiler outputs across
future MSYS2 updates.

To prepare sources locally with Python 3.11 or later:

```text
python tools/ffmpeg-build/fetch_sources.py
python tools/ffmpeg-build/package.py --source-only
```

The second command produces `tools/ffmpeg-build/dist/*-source-inputs.tar.xz`.
It contains the complete unmodified upstream source tarball, signature, public
key and this recipe. It is an input bundle, not evidence of a finished binary.
After extracting it, copy `upstream/*` into
`recipe/tools/ffmpeg-build/downloads/` and run `fetch_sources.py` there.

For a local compile, install the packages listed in the workflow and run
`bash tools/ffmpeg-build/build.sh` in the MSYS2 MINGW64 shell, followed by
`python tools/ffmpeg-build/verify.py` for offline checks. Only the GitHub-hosted
Windows runner may run `verify.py --tls-ci`: it temporarily trusts one generated
test CA and removes that exact CA afterwards. The user's certificate store is
never used for development tests. `package.py` requires successful hosted-runner
TLS verification before creating the distributable pair.

The completed workflow produces these matched release assets:

- `ffmpeg-8.1.2-hdusign-audio-win64.zip`: a `ffmpeg/` directory containing
  `ffmpeg.exe`, `LICENSE`, `README.txt`, `license-notice.txt`, `version.txt`,
  `buildconf.txt`, `SOURCE.json` and compiler-runtime license notices.
- `ffmpeg-8.1.2-hdusign-audio-source.tar.xz`: complete upstream source and its
  verification material, exact recipe/workflow and the successful build record.
- `SOURCE.json` and `SHA256SUMS`: tie the executable and the corresponding source
  archive to the same verified build. Publish the source asset alongside the ZIP.

`SOURCE.json` uses `version: "8.1.2-hdusign-audio"`, `tls_backend: "schannel"`,
`binary_sha256`, `source_archive` (an object containing `name` and `sha256`), and
`configure_flags`. No executable is accepted by the packager after it changes
following verification.

## Audio scope and application integration

HTTP(S)-FLV is the only remote container used by HDUSign. HLS is disabled.
The build retains common internal audio decoders and local WAV, AAC, MP3, FLAC,
Ogg, Matroska and MP4/MOV demuxers. AAC encoding and ADTS output support the
existing `check_ffmpeg_runtime` round trip. Resampling, stereo-to-mono conversion
and 16 kHz float32 pipe output are checked with a synthetic recording. No video
decoder, playback window or capture device is enabled. FLV output is included
only to generate the local HTTPS test fixture.

For a bundled executable whose checked `SOURCE.json` says Schannel, retain
`-tls_verify 1` and omit `-ca_file` and the certifi-file precondition. Schannel
uses the Windows certificate store; the FFmpeg Schannel implementation never
reads its `ca_file` field. For a separately installed OpenSSL/GnuTLS FFmpeg,
certifi can remain applicable. Do not infer the TLS backend from the presence
of the generic `tls` protocol alone.

In FFmpeg n8.1.2, `libavformat/tls_schannel.c` enables
`SCH_CRED_AUTO_CRED_VALIDATION | SCH_CRED_REVOCATION_CHECK_CHAIN` with
`tls_verify=1` and passes the expected host to `InitializeSecurityContext`.
This also happens for numerical IP hosts. It does not take the OpenSSL path's
numeric-host bypass. The CI verifies valid DNS and IP certificates, wrong DNS,
wrong IP and an untrusted issuer. Each rejected certificate must fail before
the HTTP request is sent. An IP string placed only in a DNS SAN is recorded but
not asserted: Windows CryptoAPI accepts it, public CAs do not issue such names,
and HDUSign only connects to DNS host names. A local CRL
server keeps the certificate tests independent of public services while still
exercising chain-revocation verification.

Certificate-test stderr is retained with synthetic stream URLs and pointer
addresses removed. The application can use those Schannel failure examples
to classify terminal certificate errors without retaining stream credentials.
The recipe does not change `hdusign/media.py` or `tools/release.py`.
