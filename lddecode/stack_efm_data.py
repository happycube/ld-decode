"""Reference-free multi-capture EFM data-image stacker (LV-ROM / Domesday).

Stacks N ``ld-process-efm -b`` data images of the same disc side into one
error-corrected image, WITHOUT needing an external reference image.

Why alignment is needed: each capture's data image is positioned by the absolute
CD-ROM sector address read from the disc, but the address origin depends on which
sector the lead-in first locked onto, so two captures of the same side do NOT
share a byte origin (e.g. one starts the volume header at sector 189, another at
182). A naive index-wise OR-merge therefore mixes mis-aligned sectors and
corrupts the result.

This tool instead aligns every capture to the FIRST capture's frame by robust
multi-anchor consensus: it picks many distinctive high-entropy sectors from the
base image, locates each one in the other capture, and takes the *modal* sector
offset -- so a few sectors a capture happens to have missed or mis-decoded cannot
throw off the alignment. It then takes, per sector, the majority value among the
captures that decoded it (>=2 agree -> consensus; else the single decoded value;
else left blank). The output is in the base capture's frame and includes the
lead-in / volume header.

Usage:
    stack_efm_data.py <out.bin> <cap0.bin> <cap1.bin> [cap2.bin ...]

See also compare_efm_data.py to validate the result against a reference image.
"""
import sys
import numpy as np
from collections import Counter

SEC = 2048


def load(path):
    a = np.fromfile(path, np.uint8)
    n = len(a) // SEC
    return a[:n * SEC].reshape(n, SEC)


def anchors(base, k=600):
    """Distinctive base sectors: present and high byte-diversity (won't false-match)."""
    pres = np.where(base.any(1))[0]
    out = []
    step = max(1, len(pres) // (k * 4))
    for s in pres[::step]:
        if len(np.unique(base[s])) > 48:
            out.append(int(s))
            if len(out) >= k:
                break
    return out


def offset_to(base, other, anch):
    """Modal sector offset such that other[p + off] corresponds to base[p]."""
    blob = other.tobytes()
    offs = []
    for s in anch:
        loc = blob.find(base[s].tobytes())
        if loc >= 0 and loc % SEC == 0:
            offs.append(loc // SEC - s)
    if not offs:
        return None, 0, 0
    off, cnt = Counter(offs).most_common(1)[0]
    return off, cnt, len(offs)


def align(other, off, n):
    """Shift ``other`` into the base frame of length n: out[p] = other[p + off]."""
    out = np.zeros((n, SEC), np.uint8)
    p = np.arange(n)
    src = p + off
    v = (src >= 0) & (src < len(other))
    out[p[v]] = other[src[v]]
    return out


def stack(paths, log=print):
    """Align all captures to the first and return the consensus (stacked) image."""
    caps = [load(p) for p in paths]
    base = caps[0]
    n = len(base)
    anch = anchors(base)
    aligned = [base]
    log(f"base = {paths[0]} ({n} sectors); {len(anch)} anchors")
    for p, c in zip(paths[1:], caps[1:]):
        off, cnt, tried = offset_to(base, c, anch)
        if off is None:
            log(f"  {p}: NO alignment found -- skipped")
            continue
        aligned.append(align(c, off, n))
        log(f"  {p}: offset {off:+d} (consensus {cnt}/{tried} anchors)")
    A = np.stack(aligned)
    present = A.any(2)
    # start from OR-fill (first decoded value per sector)
    out = A[0].copy()
    for k in range(1, len(A)):
        z = ~out.any(1) & present[k]
        out[z] = A[k][z]
    # sectors where the decoded captures disagree -> majority vote
    dis = np.zeros(n, bool)
    for i in range(len(A)):
        for j in range(i + 1, len(A)):
            both = present[i] & present[j]
            dis |= both & ~(A[i] == A[j]).all(1)
    nd = np.where(dis)[0]
    voted = 0
    for s in nd:
        vals = [tuple(A[k][s]) for k in range(len(A)) if present[k, s]]
        common, c = Counter(vals).most_common(1)[0]
        if c >= 2:
            nv = np.frombuffer(bytes(common), np.uint8)
            if not np.array_equal(nv, out[s]):
                out[s] = nv
                voted += 1
    cov = int(present.any(0).sum())
    log(f"  stacked: {n} sectors, {cov} present ({100 * cov / n:.2f}%), "
        f"{len(nd)} disagreeing sectors resolved by majority ({voted} changed)")
    return out


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    if len(argv) < 3:
        sys.exit("usage: stack_efm_data.py <out.bin> <cap0.bin> <cap1.bin> [cap2.bin ...]")
    out_path, paths = argv[0], argv[1:]
    out = stack(paths)
    out.reshape(-1).tofile(out_path)
    print(f"  -> {out_path}")


if __name__ == "__main__":
    main()
