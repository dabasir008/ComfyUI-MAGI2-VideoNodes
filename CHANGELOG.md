# Changelog

## 0.2.0

- Added dedicated Image to Video and First / Last Frame nodes.
- Added Multi Image Reference with ten native sockets and support for different image dimensions.
- Added Video Reference and Audio Reference with five native sockets each and aggregate-duration validation.
- Added Recover Task Result, requiring only a task ID and never submitting generation.
- Kept the two original node IDs and their workflow inputs compatible.
- Added six visual workflows and their API examples: ten workflows / twenty JSON files in total.
- Included the optional real HTTP / PyAV MP4 check in GitHub Actions.

## 0.1.0

- Two nodes: MAGI-2 Text to Video and MAGI-2 Image / Multimodal Reference Video.
- Dedicated first-frame and first/last-frame API modes, plus image/video/audio references.
- Native media uploads, native VIDEO output, saved MP4 preview and task receipts.
- Task-ID resume, bounded polling, credential redaction, no automatic generation retries.
- Four visual workflows and four corresponding API examples.
