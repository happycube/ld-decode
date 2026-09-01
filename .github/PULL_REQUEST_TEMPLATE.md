### Checklist

<!--
✅ Please make sure that you have completed the following steps before submitting the pull request:
-->

- [ ] I have searched the open pull requests to confirm this change has not already been submitted.
- [ ] My branch is up to date with the target branch.
- [ ] I have tested my changes and all existing tests pass.
- [ ] I have updated documentation where necessary.
- [ ] My code follows the project's coding standards (see [CONTRIBUTING.md](CONTRIBUTING.md)).

### Description

<!--
Provide a clear and concise description of the changes in this pull request.
-->

### Motivation

<!--
Why is this change needed? What problem does it solve or what improvement does it make?
-->

### Related Issues

<!--
Link any related issues here using GitHub keywords.
For example: Fixes #123, Related to #456
-->

### Changes Made

<!--
List the key changes made in this pull request.
-->

- 
- 
- 

### Testing

<!--
This is the checklist from TESTING.md, which explains what each line is for.
Tick what applies; the "For ..." lines only bite for the kind of change they name.
-->

- [ ] The unit lane passes: `python -m pytest -q tests/unit`
- [ ] The functional lane passes, or is untouched: `ctest --test-dir build --output-on-failure`
- [ ] Unit tests added or updated in the same PR as the behaviour change.
- [ ] Every new test is marked `unit` or `functional`, and labelled to match in CMake where registered.
- [ ] Unit tests touch no filesystem, network, subprocess or clock.
- [ ] Every generator is seeded; every float assertion carries a stated tolerance.
- [ ] The layer boundaries in [AGENTS.md](AGENTS.md) §2 still hold.
- [ ] For decode changes: the serial/threaded comparisons and the CVBS verifier still pass.
- [ ] For format changes: the relevant page under `docs/technical/` is updated.
- [ ] Any intentional skip is documented in the test body with a reason.
- [ ] Tested manually with: <!-- describe your test case, or N/A -->

### Screenshots (if applicable)

<!--
If your changes affect the UI or produce visual output, add screenshots here.
-->

### Additional Notes

<!--
Is there anything else reviewers should know? Any areas of concern, known limitations, or follow-up work?
-->
