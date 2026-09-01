# Testing vision and strategy

## Common

### Vision

Good software should have the following traits:
- It is easy to modify/maintain
- It is easy to test quickly and automatically
- It is easy to use

ld-decode adds a fourth, specific to signal processing:
- **Its numerical output is reproducible.** The same input and the same options must produce the
  same bytes, on one thread or on many.

### Strategy to implement vision

#### Architecture

```
MONOLITH PATTERN                    DEPENDENCY INVERSION PATTERN
  ┌─────────────────────┐             ┌────────────────┐   ┌──────────────────────┐   ┌──────────────────────┐
  │                     │             │                │   │  «Protocol»          │   │  «Protocol»          │
  │  ┌───────────────┐  │             │                ├──►│  method B()          │   │  method C()          │
  │  │ public        │  │             │  Class         │   ├──────────────────────┤   ├──────────────────────┤
  │  │ method A()    │  │             │  public        │   │  Implementation      ├──►│  Implementation      │
  │  ├───────────────┤  │    ════►    │  method A()    │   │  method B()          │   │  method C()          │
  │  │ private       │  │             │                │   └──────────────────────┘   └──────────────────────┘
  │  │ _method_b()   │  │             │                │
  │  ├───────────────┤  │             └────────────────┘
  │  │ private       │  │
  │  │ _method_c()   │  │                  class 1          collaborator 2 (injected)   collaborator 3 (injected)
  │  └───────────────┘  │
  │                     │
  │  monolithic class 1 │
  └─────────────────────┘
```

Instead of writing monolithic classes (as in the above example), we build smaller units that depend
on abstractions rather than on concrete objects they construct themselves.

Python has no `interface` keyword, so an "abstraction" here is one of:
- a **callable** the caller supplies (`read_fn`, `demod_fn`, `writer`),
- a **`typing.Protocol`** describing the methods a collaborator must provide, or
- an **abstract base class** where a shared implementation is genuinely useful.

Depending on abstractions instead of concrete objects is the Dependency Inversion design pattern.

Examples in the code (at the time of writing):
- `DemodBlockCache` — receives `read_fn` and `demod_fn`, so tests drive it with synthetic blocks.
- `make_loader` — returns a loader callable, so the decoder never names a file format directly.

##### How units receive their dependencies

Instead of a unit constructing its dependency (and so being tightly coupled to it), we *inject* the
dependency through the constructor or the call:

```python
# Hard to test: the cache reaches out and builds the world it needs.
class DemodBlockCache:
    def __init__(self, decoder):
        self.reader = open(decoder.infile, "rb")

# Easy to test: the world is handed in.
class DemodBlockCache:
    def __init__(self, read_fn, demod_fn, *, workers=4):
        self.read_fn = read_fn
        self.demod_fn = demod_fn
```

Keyword-only arguments with defaults keep the constructor readable as collaborators are added.

**Important:** where the object needs post-construction setup (a filter design pass, a warm-up),
keep it in a separate `init`/`configure` method on the concrete class rather than in the protocol.
It is an implementation detail, and only the code that instantiates the object should know about it.

##### What if the unit needs to create objects dynamically, such as opening a file?

Inject a **factory** — a callable that returns the collaborator. `lddecode.fileio.make_loader` is the
pattern to follow: it maps a filename to a loader callable, and everything downstream depends only on
"something I can call with an offset and a length".

##### Where computation should live

Push pure computation as far down the layering in `AGENTS.md` §2 as it will go. A function that takes
arrays and constants and returns arrays is trivially unit testable; the same maths embedded in a
method that also opens files and logs progress is not. When a unit test is hard to write, the usual
cause is that the maths and the I/O have not been separated — fix that rather than reaching for a
functional test.

#### Testing architecture

```
FUNCTIONAL TEST PATTERN                     UNIT TEST PATTERN
  ┌──────────────────────────┐               ┌─────────────────────┐   ┌─────────────────────┐   ┌─────────────────────┐
  │ Functional test for      │               │ Unit test for       │   │ Unit test for       │   │ Unit test for       │
  │ method C. Must also      │               │ method A            │   │ method B            │   │ method C            │
  │ exercise A and B, and    │               └──────────┬──────────┘   └──────────┬──────────┘   └──────────┬──────────┘
  │ needs real capture data. │                          │                         │                         │
  └────────────┬─────────────┘                          ▼                         ▼                         ▼
               │                              ┌─────────────────────┐   ┌─────────────────────┐   ┌─────────────────────┐
               ▼                              │  «Unit»             │   │  «Unit»             │   │  «Unit»             │
  ┌────────────────────────┐                  │  method A()         │   │  method B()         │   │  method C()         │
  │  ┌──────────────────┐  │    ════►         └──────────┬──────────┘   └──────────┬──────────┘   └─────────────────────┘
  │  │ public           │  │                             │                         │
  │  │ method A()       │  │                             ▼                         ▼
  │  ├──────────────────┤  │                  ┌─────────────────────┐   ┌─────────────────────┐
  │  │ private          │  │                  │ Fake/mock supplying │   │ Fake/mock supplying │
  │  │ _method_b()      │  │                  │ method B()          │   │ method C()          │
  │  ├──────────────────┤  │                  └─────────────────────┘   └─────────────────────┘
  │  │ private          │  │
  │  │ _method_c()      │  │                   unit test for only        unit test for only       unit test for only
  │  └──────────────────┘  │                   method A                  method B                 method C
  │                        │
  │  slow, hard-to-        │
  │  maintain test         │
  └────────────────────────┘
```

##### Encapsulation

Get into the mindset of not testing your dependencies' internal implementations. You give a
dependency inputs and expect certain outputs. It is not your job to test how it computes them, or
even to know. Trying to do so leads to tight coupling and bad architecture.

Staying intentionally ignorant of how dependencies are implemented internally is encapsulation.
Practising it makes the project easy to modify and maintain: any module is free to change its
implementation without breaking the rest of the project, because everything else depends on stable
abstractions rather than on concrete classes.

##### Unit tests

Unit tests are small, lightweight tests that exercise a small bit of code, usually a single function
or method.

Benefits of a large suite of unit tests:
- They execute extremely quickly (thousands of tests in seconds)
- They are effective at digging into corner cases that would otherwise be difficult or slow to test
  automatically — and in DSP code the corner cases are where the bugs are
- They encourage encapsulation, which tends to make the project easier to modify and maintain
- They are self-contained, so they need no 'tribal knowledge' to set up — no capture files, no
  submodules, no external tools
- If they fail, it is easy to pinpoint the source of the problem

**Rules for unit tests (non-negotiable):**

- All dependencies are mocked or injected. Unit tests never touch the file system, the network, a
  database, a subprocess, or the system clock. This makes them deterministic, which is very
  desirable.
- They usually test a single function. If a function calls a small private helper, the test
  necessarily covers two functions; that is usually fine if the helper is trivial, but large private
  helpers are an anti-pattern and should be moved into their own unit.
- **Every input is constructed in the test.** Synthesise the signal — a sine, a step, a sync pulse
  built from `params.py` constants — rather than loading a capture.
- **Every source of randomness is seeded.** `rng = np.random.default_rng(12345)`; never bare
  `np.random.*`.
- **Every float comparison states a tolerance.** Use `np.testing.assert_allclose(actual, expected,
  rtol=…, atol=…)` and say in a comment why that tolerance is the right one. Bit-exact comparisons
  are for integer and byte-level formats only.
- **Import the owning module, not the facade.** `from lddecode.field import Field`, never
  `from lddecode.core import *`.
- Rule of thumb: unit tests should make up 80% of all tests in a well-designed project.

##### Functional tests

Functional tests exercise multiple functions, often the whole pipeline, to establish that a section
of the project works end to end. In ld-decode they are the tests that decode a real `.ldf` capture
from `testdata/` and check the result.

They execute slowly, are poor at digging into corner cases, tend to be larger and harder to maintain,
and are harder for a newcomer to set up. They may use the file system, subprocesses, and external
tools, so they are harder to troubleshoot when something goes wrong.

Use them for a few 'happy path' cases, to confirm everything is wired up correctly, and for the
properties that only exist at the whole-pipeline level:

- **Format conformance** — the `.cvbs` output satisfies `analysis/cvbs_verify.py` against
  `cvbs-file-format-specification/`.
- **Serial/threaded bit-identity** — `-t 8 --exact-speculation` produces byte-identical output to the
  serial decode. Any divergence is a real concurrency bug.
- **Round-trip fidelity** — `.lds` pack/unpack and `ld-compress`/decompress change no bytes.
- **Signal quality** — the expected VITS and test patterns are present and measurable in the decoded
  output.

Anything that can be established with synthetic data belongs in a unit test instead.

##### Mocks and fakes

A *mock* stands in for a collaborator during a unit test. It returns the expected result when given
the expected arguments. It specifically does **not** implement real functionality.

For example, a mock of a *multiply* method returns 12 when it receives 3 and 4. It does not actually
multiply. Going down the road of implementing real multiplication in a test is going down the road to
tight coupling. Discipline yourself not to test your dependencies' implementations.

Python gives you three tools; prefer them in this order:

1. **A hand-written fake closure** — best for anything array-shaped. A `read_fn` that returns
   `np.arange(...)` for block *b* is clearer and faster than any framework, and the test can assert
   on a log of the calls it received. See the `make_fns` helper in
   `tests/test_parallel_blockcache.py`.
2. **`unittest.mock.Mock` / `MagicMock`** — best when you want to assert on *how* a collaborator was
   called (`assert_called_once_with`, `call_args_list`).
3. **`monkeypatch`** (pytest fixture) — last resort, for replacing a module-level name that is not
   yet injectable. Every use of `monkeypatch` on production code is a hint that a seam is missing;
   prefer adding the injection point.

###### Should I mock a class or a protocol?

Mock the **protocol** — the small set of methods the unit under test actually calls. Mocking a
concrete class risks side effects creeping through: inherit from it and forget to override one
method, and the real implementation runs inside your "unit" test. `unittest.mock.create_autospec`
gives you the signature checking without the behaviour.

Sometimes mocking a class is unavoidable; when you do, say why in the test.

###### What must always be faked in a unit test

| Real thing | Fake it with |
|------------|--------------|
| A capture file | A NumPy array built in the test, or `io.BytesIO` for byte streams |
| `open()` / a loader | An injected loader callable returning synthetic samples |
| A subprocess (`ffmpeg`, `flac`, `orc-cli`) | An injected runner, or move the test to the functional lane |
| A thread pool | A synchronous executor, or the real pool with a deterministic work function |
| `time.time()` / `time.monotonic()` | An injected clock callable |
| `np.random` | `np.random.default_rng(seed)` passed in |

##### Examples of unit tests

- `tests/test_cvbs_lattice.py` — integer-exact lattice arithmetic, no I/O
- `tests/test_parallel_blockcache.py` — scheduling, caching, EOF, keying and eviction driven by
  synthetic read/demod closures
- `tests/test_cx.py`, `tests/test_demod_fft.py` — filter and transform maths on synthesised signals

## Test layout and labels

### Directory layout

```
tests/
├── conftest.py          # Shared fixtures; the unit/functional marker split
├── unit/                # Hermetic pytest suites — no I/O, no data, no subprocesses
└── functional/          # Suites that need real capture data or external tools
```

> **Current state.** The suites listed above still sit directly in `tests/`, and most of them are
> already hermetic unit tests. New tests go into `tests/unit/` or `tests/functional/`; existing ones
> move as they are touched. `tests/test_input_formats.py` and the subprocess-using parts of
> `tests/test_lds.py` and `tests/test_compress.py` belong in `tests/functional/`.

### pytest markers

Every test carries exactly one of `unit` or `functional`, plus an optional family marker.

| Marker | Scope |
|--------|-------|
| `unit` | Fast, hermetic; no filesystem, network, subprocess, or clock |
| `functional` | Needs real capture data, a subprocess, or a full decode run |
| `dsp` | Filter, demodulation and signal-maths tests |
| `format` | File-format tests (`.lds`, `.ldf`, `.cvbs`, `.tbc`, metadata) |
| `decode` | Field/frame assembly, sync and TBC logic |
| `parallel` | Threading, block-cache and speculation |
| `slow` | Functional tests exceeding roughly 60 s |

Markers must be registered in `pyproject.toml` under `[tool.pytest.ini_options] markers` so an
unregistered marker is an error rather than a silent no-op. Apply them per module where a whole file
shares a marker:

```python
import pytest

pytestmark = [pytest.mark.unit, pytest.mark.format]
```

Anything under `tests/functional/` that does not have its data available must **skip**, not fail:

```python
pytest.importorskip("...")                       # optional dependency
pytest.mark.skipif(not TESTDATA.exists(), reason="testdata submodule not checked out")
```

### CTest labels

CTest is the outer driver; its labels mirror the pytest markers so the same slice can be requested
from either side.

| Label | Scope |
|-------|-------|
| `unit` | The hermetic pytest lane (`tests/unit/`) |
| `functional` | Decode, comparison, analysis, cut, and compress tests over `testdata/` |
| `slow` | Functional tests exceeding roughly 60 s |

Label assignment rules:
- Every test registered in [cmake_modules/LdDecodeTests.cmake](cmake_modules/LdDecodeTests.cmake)
  must carry exactly one of `unit` or `functional`:

  ```cmake
  set_tests_properties(python-unit-tests PROPERTIES LABELS "unit")
  set_tests_properties(decode-ntsc-basic PROPERTIES LABELS "functional;slow")
  ```
- The `unit` lane must invoke pytest over `tests/unit/` only, so it stays hermetic and fast.
- Functional tests that produce inputs for other tests use `FIXTURES_SETUP`/`FIXTURES_REQUIRED`
  rather than `DEPENDS` where a shared artefact is involved, so a filtered run still sets up what it
  needs.
- Every functional test sets an explicit `TIMEOUT`.

### Unit/functional boundary guard

- A file under `tests/unit/` must not contain `open(`, `subprocess`, `tmp_path`, `requests`, or a
  reference to `testdata`. Treat any occurrence as a review failure.
- A test that needs the `testdata/` submodule lives under `tests/functional/` and is registered with
  CTest, not in the fast pytest lane.

## How to run the tests

All commands assume the Nix development shell. Prefix with `nix develop --command` if you are not
already inside it.

### Unit tests (fast path during development)

```bash
# Everything hermetic
python -m pytest -q tests/unit

# One file
python -m pytest -v tests/unit/test_cvbs_lattice.py

# One test by name
python -m pytest -q -k "pal_lattice"

# One family
python -m pytest -q -m "unit and dsp"

# With coverage
python -m pytest -q --cov=lddecode --cov-report=term-missing tests/unit

# Stop at the first failure, with local variables in the traceback
python -m pytest -x -l tests/unit
```

### Functional tests

Functional tests need the `testdata/` submodule:

```bash
git submodule update --init --recursive testdata     # only when the user asks
```

Then:

```bash
# Configure (this also regenerates lddecode/version from git)
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release

# Fast lane only
ctest --test-dir build -L unit --output-on-failure

# Functional lane only
ctest --test-dir build -L functional --output-on-failure

# Everything (matches the CI expectation)
ctest --test-dir build --output-on-failure

# A single test, with its full output
ctest --test-dir build -R decode-ntsc-cvbs --output-on-failure -V

# Serial/threaded bit-identity
ctest --test-dir build -R "parallel" --output-on-failure

# In parallel, on all cores
ctest --test-dir build -L unit --parallel "$(nproc)" --output-on-failure
```

Decode outputs land in `build/testout/`; inspect them there when a comparison fails.

### What the functional lane covers

| Test group | What it establishes |
|------------|---------------------|
| `decode-ntsc-basic`, `decode-pal-basic` | A real capture decodes to `.tbc` without error |
| `decode-*-parallel` + `compare-*-parallel-*` | Threaded decode is **byte-identical** to serial |
| `decode-*-cvbs` + `verify-*-cvbs` | `.cvbs` output conforms to the format specification |
| `roundtrip-*-orc` | Rendering CVBS and TBC through the same chroma decoder agrees (skips without `orc-cli`) |
| `analyze-*-patterns`, `analyze-ntsc-ntc7` | Expected VITS/test patterns are present and measurable |
| `input-format-loaders` | Every raw input format reads back exactly, aligned and unaligned |
| `cut-*`, `decode-*-cut`, `decode-ntsc-lds` | `ld-cut` output is well-formed and decodable |
| `compress-lds-round-trip` | `ld-compress` changes no bytes (skips without `flac`) |

These are contracts. If a change makes one fail, the change is wrong until proven otherwise — do not
relax a `PASS_REGULAR_EXPRESSION`, widen a tolerance, or delete a comparison to get green.

## Adding a test

### Adding a unit test

1. Put it under `tests/unit/`, named `test_<module>_<behaviour>.py`.
2. Mark it: `pytestmark = [pytest.mark.unit, pytest.mark.<family>]`.
3. Import the owning module directly, not `lddecode.core`.
4. Build every input in the test; seed every generator.
5. Assert with an explicit tolerance, and comment why that tolerance is right.
6. Run `python -m pytest -q tests/unit` and confirm it is fast.

```python
"""Unit tests for the PAL 4fsc line lattice."""

import pytest

from lddecode.cvbs import PAL_FRAME_LINES, PAL_FRAME_SAMPLES, pal_line_lattice

pytestmark = [pytest.mark.unit, pytest.mark.format]


def test_pal_lattice_slips_four_samples_per_frame():
    # EBU Tech. 3280-E: fsc is not line-locked, so 625*1135 + 4 = 709,379.
    counts = [n for _, n, _ in pal_line_lattice()]
    assert len(counts) == PAL_FRAME_LINES
    assert sum(counts) == PAL_FRAME_SAMPLES
    assert counts.count(1136) == 4
```

### Adding a functional test

1. Confirm it genuinely cannot be a unit test. Say why in the module or CMake comment.
2. Put the Python under `tests/functional/`, or register the command directly in
   `cmake_modules/LdDecodeTests.cmake`.
3. Add `LABELS "functional"` (plus `slow` where it applies) and an explicit `TIMEOUT`.
4. Use `FIXTURES_SETUP`/`FIXTURES_REQUIRED` for artefacts shared with other tests.
5. Where the test asserts on an `analysis/` script's output, pin it with
   `PASS_REGULAR_EXPRESSION`, and give the script a `SKIP_REGULAR_EXPRESSION` path if it depends on
   an optional external tool.
6. Write outputs under `${CMAKE_BINARY_DIR}/testout/` — never into the source tree.

```cmake
add_test(
    NAME decode-pal-cvbs
    COMMAND ${CMAKE_SOURCE_DIR}/ld-decode --cvbs --PAL -l 6
        ${TESTDATA_DIR}/pal/ggv-mb-1khz.ldf
        ${CMAKE_BINARY_DIR}/testout/pal-cvbs
    WORKING_DIRECTORY ${CMAKE_BINARY_DIR}
)
set_tests_properties(decode-pal-cvbs PROPERTIES
    LABELS "functional;slow"
    FIXTURES_SETUP pal-cvbs
    TIMEOUT 600
)
```

## Testing DSP code

Signal-processing code has its own failure modes. These conventions keep the tests honest.

- **Synthesise, don't sample.** Build the test signal from first principles: a sine at a known
  frequency, an impulse, a step, a sync pulse constructed from `params.py`. You then know the exact
  answer, which a real capture never gives you.
- **Test properties, not just values.** A filter has a passband gain, a stopband rejection, a group
  delay, and a known impulse response length. Assert those. A "golden array" of 4,096 floats tells
  you a change happened, not what broke.
- **State tolerances in signal terms.** "Within 0.1 IRE", "within one sample", "within 0.5 degrees of
  differential phase" — not `rtol=1e-7` chosen because it happened to pass.
- **Cover the boundaries.** Empty input, single sample, exactly one block, one sample either side of
  a block boundary, the first and last line of a field, first and last field of a frame.
- **Pin the integer maths exactly.** Lattice arithmetic, `.lds` packing, byte layouts and metadata
  are integer or byte problems: assert exact equality there, and use `fractions.Fraction` rather than
  floats in the test's own arithmetic.
- **Numba:** `@njit` functions are testable like any other. Set `NUMBA_DISABLE_JIT=1` when you need a
  readable traceback or accurate coverage, but let at least one test run compiled so a Numba-typing
  regression is caught.
- **Don't test the library.** SciPy's `filtfilt` works; test the filter *you* designed and how you
  applied it.

## CI gate slices

The CI pipeline runs the whole CTest suite as the required gate for every push and pull request.

- Primary gate workflow: [.github/workflows/build-and-test.yml](.github/workflows/build-and-test.yml)
  - Checks out submodules recursively (so `testdata/` is present).
  - Enters the Nix dev shell, configures CMake in `build/`, and runs `ctest --output-on-failure -V`.
  - Packaging workflows (AppImage, macOS DMG, Windows ZIP) run only after it passes.
- Manual functional lane: [.github/workflows/functional-tests.yml](.github/workflows/functional-tests.yml)
  - The same run, on `workflow_dispatch`, for re-checking without a push.

Reference invocations (local equivalent):

```bash
# Primary gate equivalent
nix develop .#default -c bash -lc '
  mkdir -p build/testout
  cd build
  cmake -DCMAKE_BUILD_TYPE=Release ..
  ctest --output-on-failure -V
'

# Fast slice only — what to run while iterating
nix develop --command python -m pytest -q tests/unit
nix develop --command ctest --test-dir build -L unit --parallel "$(nproc)" --output-on-failure
```

## PR checklist

- Unit tests added or updated in the same PR as the behaviour change.
- Every new test marked `unit` or `functional`, and labelled to match in CMake where registered.
- Unit tests touch no filesystem, network, subprocess, or clock.
- Every generator seeded; every float assertion carries a stated tolerance.
- The layer boundaries in `AGENTS.md` §2 still hold.
- For decode changes: serial/threaded comparisons and the CVBS verifier still pass.
- For format changes: the relevant page under `docs/technical/` updated.
- Any intentional skip documented in the test body with a reason.
