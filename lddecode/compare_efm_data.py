"""Validate a stacked EFM data image against a reference image.

Aligns the data image to the reference (constant sector offset, found by locating
the reference's first non-blank sector inside the image), then reports byte
agreement and coverage over the reference's data sectors:

  * reproduced byte-identical,
  * MISSED  (reference has data, our image is blank there),
  * present-but-DIFFER (both have data but it differs -- a reference defect if the
    stacked captures agree among themselves, see stack_efm_data.py).

Blank (sparse-zero) reference sectors are ignored. Useful to check a stack from
stack_efm_data.py against a known-good reference (e.g. a .ldi).

Usage: compare_efm_data.py <data.bin> <reference.bin>
"""
import sys
import numpy as np

SEC = 2048


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    if len(argv) != 2:
        sys.exit("usage: compare_efm_data.py <data.bin> <reference.bin>")
    dataf, reff = argv
    img = np.fromfile(dataf, np.uint8)
    ref = np.fromfile(reff, np.uint8)
    nimg, nref = len(img) // SEC, len(ref) // SEC
    imgs = img[:nimg * SEC].reshape(nimg, SEC)
    refs = ref[:nref * SEC].reshape(nref, SEC)
    print(f"data image: {nimg} sectors ({nimg * SEC / 1e6:.1f} MB);  reference: {nref} sectors")

    # locate reference's first non-blank sector inside the image -> constant offset
    ref_first = int(np.argmax(refs.any(1)))
    probe = refs[ref_first].tobytes()
    loc = img.tobytes().find(probe)
    if loc < 0 or loc % SEC:
        sys.exit(f"!! could not sector-align reference[{ref_first}] in image (loc={loc})")
    off = loc // SEC - ref_first
    print(f"alignment: reference sector {ref_first} == image sector {loc // SEC}  ->  OFFSET = {off}")

    n = min(nref, nimg - off)
    sub = imgs[off:off + n]
    r = refs[:n]
    eq = (sub == r).all(1)
    refdata = r.any(1)                      # non-blank reference sectors
    nd = int(refdata.sum())
    miss = refdata & ~eq & ~sub.any(1)
    differ = refdata & ~eq & sub.any(1)
    print(f"\noverlap: {n} sectors;  reference data sectors: {nd}")
    print(f"  reproduced byte-identical: {int((refdata & eq).sum())} "
          f"({100 * (refdata & eq).sum() / max(nd, 1):.4f}%)")
    print(f"  MISSED (blank in image):   {int(miss.sum())}")
    print(f"  present-but-DIFFER:        {int(differ.sum())}")

    print("\nband (ref-sec)   ref_data  match%")
    for a in range(0, n, 10000):
        b = min(a + 10000, n)
        sl = slice(a, b)
        hd = refdata[sl]
        c = int(hd.sum())
        if c == 0:
            print(f"  {a:7d}-{b:7d}  {c:7d}   (blank)")
        else:
            print(f"  {a:7d}-{b:7d}  {c:7d}   {100 * (eq[sl] & hd).sum() / c:6.2f}%")


if __name__ == "__main__":
    main()
