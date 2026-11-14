# Source and publication boundary

Public source contains reusable code, public documentation and synthetic tests.
Populated profiles, learner responses, personal catalogs, original private
exports and local runtime databases belong outside public git. Credentials
belong in a secret manager or runtime configuration, never source control.
Commercially distinctive private code requires an explicit interface and
licensing decision; this policy does not claim that component split is complete.

Choose a dedicated, trusted input directory containing only sources you intend
to ingest. Ingestion does not determine whether arbitrary text is sensitive or
licensed for use. Do not scan a home directory or a mixed private/public archive.
The default discovery excludes `.private`, `.secrets`, `.adaptive-syllabus` and
tool caches. Explicit exclusion paths also exclude their descendants.

Symlinked files and directories are not admitted. Sources are opened relative
to a directory descriptor with no-follow flags for each component, so replacing
a selected file or parent with a symlink fails before snapshot persistence.
Secure opening currently requires POSIX directory-descriptor/no-follow support;
unsupported platforms fail closed. This protects against symlink traversal, not
a hostile filesystem owner, hard-link admission, or changes to source contents
while they are read. The selected input root must be trusted.

PDF/DOCX discovery remains metadata-only until extraction is implemented and
verified. A source hash or matching filename is not evidence of passage support.

Do not report sensitive findings in public issue text. Use a private maintainer
channel or repository private vulnerability reporting if enabled. If neither is
available, request a private channel without including the sensitive material.
Do not assume an unavailable reporting feature is enabled.

Removing a tracked file is not evidence that historical disclosure has been
reversed. Preserve custody and review history, published artifacts, permissions
and any required credential rotation separately. Issues #23, #33, #34 and #42
track the remaining boundary work.
