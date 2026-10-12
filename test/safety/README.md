# Safe bootstrap regression tests

Run `python -m unittest discover -s test/safety -v` from the repository root.
The tests extract function definitions only. They never source bootstrap's top-level,
run the installer, operate a block device, mount a filesystem, or configure services.
All invoked disk commands are shell functions backed by synthetic fixtures. Timeout
coverage simulates exit 124; it does not demonstrate a physical device timing out.

## Candidate baseline

Baseline: honjow/frzr stable = peeled tag 3.5.3 =
569307df84be8d0653430d4fa94f93b89d261ccd. Live `git ls-remote` checked
2026-10-12. Annotated tag object f428e15a347082df58b352cba609f26ccc5de143.
The same check found dev=9d867af972825c7352576adb36446641f3f25cbb and
uki=09833b8d259c164e2a1af448b970f58e34291fd5; neither is this candidate's base.

## Detection and cleanup protocol

`inspect_frzr_installation`: 0 complete, 1 none, 2 incomplete, 3 ambiguous,
4 unknown. These are layout/label classifications, not verification that a deployed
OS's content is valid. Snapshot is bounded to 15 seconds. Exact labels, filesystem
types, partition identities and a single selected disk are required. Foreign-disk
frzr labels, similar labels, duplicate labels/identities or incompatible filesystems
block execution conservatively. Multi-disk layouts require manual review rather than
being guessed supported. Missing/failed/malformed reads never become none.

`check_existing_installation` has no implicit cleanup. Optional cleanup requires BOTH:
- FRZR_CLEANUP_DISK: exact selected disk path
- FRZR_CLEANUP_PARTITIONS: newline-separated `path|PARTUUID` entries, exactly the
  current set of frzr_efi/frzr_root/frzr_home partitions on that disk

The caller must obtain explicit approval listing these partitions and explaining
that deletion destroys their contents. frzr_home and home subvolumes inside frzr_root
can contain user data. The caller must construct these variables from that approval,
never inherit stale cleanup environment. Current UI can refuse incomplete layouts
without exposing a cleanup option. Ambiguous/unknown states are not cleanup-eligible.
Before deletion the backend re-reads and matches the entire identity set. Failures
abort and propagate; after partprobe another snapshot must classify the disk as none.
This reduces stale-plan risk but is not a transactional guarantee against hotplug
between the last read and a kernel command. Real-device VM tests remain required.

## Cooperative cancellation

FRZR_CANCEL_FILE points to a caller-owned request file. Its existence requests a stop.
`@@FRZR_STAGE <name> safe|protected` reports boundaries on stderr. A checkpoint
exits 130 if requested, before the next protected region. Preflight and completion
are checkpoints; repair, fresh, dual and cleanup run protected. Dual is deliberately
one coarse protected region. Do not kill bootstrap based on one `safe` log line;
state can change immediately afterward. Cancellation requests are cooperative and
may wait for protected disk work to finish. Old backend versions must likewise be
considered protected. Completion cancellation does not roll back finished writes.

## Compatibility and remaining validation

Old callers can install on a clear disk or repair a unique supported layout. They
cannot silently erase incomplete installations. Partial layouts now stop, including
interactive callers without a scoped cleanup plan. Startup's unconditional unmounts
were removed so failed preflight does not change mounts. A bounded read-only mount query rejects an occupied installer mount directory
or any mounted child before entering a protected install stage. Query failure is
also blocking; existing mounts are never forcibly removed by this check.

No real Live ISO/hardware install, repair, resize or cleanup was run. Existing legacy
deploy tests source unrelated deployment code and were not executed by this suite.
Run disposable VM tests before release, including cancellation during actual I/O,
repair with separate/shared EFI, dual boot and representative device naming.

## Paired frontend protocol check

The exact top-of-file marker `# FRZR_INSTALLER_PROTOCOL=1` declares this contract.
The paired frontend reads it without executing legacy command-line flags.
`test_frontend_protocol.py` uses a sibling install-media checkout (or
INSTALL_MEDIA_ROOT) to validate the actual candidate marker, classify nine identical
synthetic inventories in both languages, and run the real frontend runner against
only the extracted shell checkpoint function. It verifies cooperative request-file
cancellation exits 130 and is reported as cancelled, with stage events preserved.
These tests never execute the full installer.

## Deployment network waits

Fallback metadata requests now use 10-second connection and 30-second per-attempt
total limits, with one retry. Image curl downloads use a 15-second connection
limit, a 120-second window below 1 byte/second, and two retries. aria2 uses a
15-second connection limit, 120-second timeout, 1-byte/second lowest speed,
maximum three tries and two-second retry wait. Healthy large image downloads have
no short total-duration cap. Every existing downloader UI branch carries the policy.
Explicit transfer-status handling prevents an unsuccessful transfer's partial file
from being treated as success when checksum is omitted and the function runs under
`if download_file` (where Bash errexit is disabled).

Tests use downloader stubs, verify all branch arguments, simulate curl exit 28
and aria2 failure, and assert failure prevents a synthetic deployment continuation.
They do not measure real curl/aria2 timing or actual slow/stalled servers.

Deployment still does not consume the cooperative cancellation file. Frontend
cancellation during deploy remains deferred until natural process-tree completion.
This patch does not kill download/extraction/btrfs operations or add a whole-deploy
timeout. Downloads with sustained progress may legitimately take a long time;
extraction, filesystem writes and kernel I/O remain without a cancellation deadline.
These are explicit remaining limits, not evidence of immediate end-to-end cancel.
