"""Minimal Compound File Binary (OLE2) reader and writer, enough for Office encrypted packages.

Only what MS-OFFCRYPTO needs: a tree of storages and streams, 512-byte sectors, mini stream,
DIFAT for files larger than ~7 MB. Pure Python, no third-party dependencies.
"""
from __future__ import annotations
import struct

SIG = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
FREE, ENDCHAIN, FATSECT, DIFSECT = 0xFFFFFFFF, 0xFFFFFFFE, 0xFFFFFFFD, 0xFFFFFFFC
NOSTREAM = 0xFFFFFFFF
SECT = 512
MINI = 64
CUTOFF = 4096


class CfbError(ValueError):
    pass


# ----------------------------------------------------------------------------- reader
def _chain(fat, start, limit):
    out, s, seen = [], start, 0
    while s != ENDCHAIN:
        if s >= len(fat) or seen > limit:
            raise CfbError("corrupt sector chain")
        out.append(s)
        s = fat[s]
        seen += 1
    return out


def read_streams(data: bytes) -> dict[str, bytes]:
    """Return {'path/to/stream': bytes} for every stream in the container."""
    if len(data) < 512 or data[:8] != SIG:
        raise CfbError("not a compound file")
    (minor, major, bo, sshift, mshift) = struct.unpack_from("<HHHHH", data, 24)
    if bo != 0xFFFE or sshift not in (9, 12):
        raise CfbError("unsupported compound file")
    ssz, msz = 1 << sshift, 1 << mshift
    nfat, dir_start, _, cutoff, mf_start, nmf, dif_start, ndif = struct.unpack_from("<IIIIIIII", data, 44)[0:1] + \
        struct.unpack_from("<IIIIIII", data, 48)
    difat = list(struct.unpack_from("<109I", data, 76))

    def sector(i):
        off = (i + 1) * ssz
        if off + ssz > len(data):
            raise CfbError("sector out of range")
        return data[off:off + ssz]

    s, n = dif_start, 0
    while s not in (ENDCHAIN, FREE) and n < ndif:
        blk = struct.unpack("<%dI" % (ssz // 4), sector(s))
        difat.extend(blk[:-1])
        s = blk[-1]
        n += 1
    fat = []
    for f in difat[:nfat]:
        fat.extend(struct.unpack("<%dI" % (ssz // 4), sector(f)))
    limit = len(fat) + 2
    dirdata = b"".join(sector(i) for i in _chain(fat, dir_start, limit))
    entries = []
    for i in range(0, len(dirdata), 128):
        e = dirdata[i:i + 128]
        nl = struct.unpack_from("<H", e, 64)[0]
        name = e[:max(nl - 2, 0)].decode("utf-16-le", "replace")
        typ = e[66]
        left, right, child = struct.unpack_from("<III", e, 68)
        start = struct.unpack_from("<I", e, 116)[0]
        size = struct.unpack_from("<Q", e, 120)[0]
        entries.append(dict(name=name, type=typ, left=left, right=right, child=child, start=start, size=size))
    if not entries or entries[0]["type"] != 5:
        raise CfbError("missing root entry")
    root = entries[0]
    ministream = b"".join(sector(i) for i in _chain(fat, root["start"], limit)) if root["start"] != ENDCHAIN else b""
    minifat = []
    if mf_start != ENDCHAIN:
        for i in _chain(fat, mf_start, limit):
            minifat.extend(struct.unpack("<%dI" % (ssz // 4), sector(i)))

    def read_stream(e):
        if e["size"] < cutoff:
            parts = []
            for i in _chain(minifat, e["start"], len(minifat) + 2):
                parts.append(ministream[i * msz:(i + 1) * msz])
            return b"".join(parts)[:e["size"]]
        return b"".join(sector(i) for i in _chain(fat, e["start"], limit))[:e["size"]]

    out = {}

    def walk(idx, prefix, seen):
        if idx == NOSTREAM or idx >= len(entries) or idx in seen:
            return
        seen.add(idx)
        e = entries[idx]
        walk(e["left"], prefix, seen)
        path = prefix + e["name"]
        if e["type"] == 2:
            out[path] = read_stream(e)
        elif e["type"] == 1:
            walk(e["child"], path + "/", seen)
        walk(e["right"], prefix, seen)

    walk(root["child"], "", set())
    return out


# ----------------------------------------------------------------------------- writer
def _cmp_key(name: str):
    return (len(name), name.upper())


def write_streams(streams: dict[str, bytes], order_hint=None) -> bytes:
    """Build a compound file from {'dir/sub/stream': bytes}. Storage names are inferred from paths."""
    # directory tree
    nodes = [dict(name="Root Entry", type=5, children={}, data=None)]
    for path, data in streams.items():
        parts = path.split("/")
        cur = nodes[0]
        for p in parts[:-1]:
            nxt = cur["children"].get(p)
            if nxt is None:
                nxt = dict(name=p, type=1, children={}, data=None)
                cur["children"][p] = nxt
            cur = nxt
        cur["children"][parts[-1]] = dict(name=parts[-1], type=2, children={}, data=data)

    flat = []

    def assign(node):
        node["idx"] = len(flat)
        flat.append(node)
        kids = sorted(node["children"].values(), key=lambda n: _cmp_key(n["name"]))
        for k in kids:
            assign(k)
        # balanced BST of siblings
        def build(lo, hi):
            if lo >= hi:
                return NOSTREAM
            mid = (lo + hi) // 2
            k = kids[mid]
            k["left"] = build(lo, mid)
            k["right"] = build(mid + 1, hi)
            return k["idx"]
        node["child"] = build(0, len(kids))

    assign(nodes[0])
    for n in flat:
        n.setdefault("left", NOSTREAM)
        n.setdefault("right", NOSTREAM)

    # place streams: small ones into mini stream, big ones into regular sectors
    ministream = bytearray()
    minifat: list[int] = []
    big: list[tuple[dict, bytes]] = []
    for n in flat:
        if n["type"] != 2:
            n["start"], n["size"] = (ENDCHAIN, 0)
            continue
        d = n["data"]
        n["size"] = len(d)
        if len(d) == 0:
            n["start"] = ENDCHAIN
        elif len(d) < CUTOFF:
            first = len(minifat)
            cnt = (len(d) + MINI - 1) // MINI
            for i in range(cnt):
                minifat.append(first + i + 1 if i < cnt - 1 else ENDCHAIN)
            ministream += d + b"\0" * (cnt * MINI - len(d))
            n["start"] = first
        else:
            big.append((n, d))

    # sector layout: [data/ministream/minifat/directory sectors..., FAT sectors..., DIFAT sectors...]
    sectors: list[bytes] = []
    fat: list[int] = []

    def add_chain(blob: bytes) -> int:
        if not blob:
            return ENDCHAIN
        cnt = (len(blob) + SECT - 1) // SECT
        first = len(fat)
        for i in range(cnt):
            fat.append(first + i + 1 if i < cnt - 1 else ENDCHAIN)
            sectors.append(blob[i * SECT:(i + 1) * SECT].ljust(SECT, b"\0"))
        return first

    for n, d in big:
        n["start"] = add_chain(d)
    root = flat[0]
    root["size"] = len(ministream)
    root["start"] = add_chain(bytes(ministream))
    mf_blob = b"".join(struct.pack("<I", x) for x in minifat)
    mf_start = add_chain(mf_blob.ljust(((len(mf_blob) + SECT - 1) // SECT) * SECT, b"\xff")) if minifat else ENDCHAIN
    n_mf = (len(mf_blob) + SECT - 1) // SECT if minifat else 0

    dirblob = bytearray()
    for n in flat:
        nm = n["name"].encode("utf-16-le")
        e = bytearray(128)
        e[:len(nm)] = nm
        struct.pack_into("<H", e, 64, len(nm) + 2)
        e[66] = n["type"]
        e[67] = 1  # black
        struct.pack_into("<III", e, 68, n["left"], n["right"], n["child"])
        struct.pack_into("<I", e, 116, n["start"])
        struct.pack_into("<Q", e, 120, n["size"])
        dirblob += e
    while len(dirblob) % SECT:
        e = bytearray(128)
        struct.pack_into("<III", e, 68, NOSTREAM, NOSTREAM, NOSTREAM)
        dirblob += e
    dir_start = add_chain(bytes(dirblob))

    # FAT sectors (and DIFAT) must describe themselves
    per = SECT // 4
    nfat = 0
    while True:
        total = len(fat) + nfat
        ndif = max(0, (nfat - 109 + per - 2) // (per - 1)) if nfat > 109 else 0
        need = (total + ndif + per - 1) // per
        if need <= nfat and (ndif == 0 or True):
            break
        nfat = need
    # recompute stable values
    ndif = max(0, (nfat - 109 + per - 2) // (per - 1)) if nfat > 109 else 0
    base = len(fat)
    fat_ids = list(range(base, base + nfat))
    fat.extend([FATSECT] * nfat)
    dif_ids = list(range(base + nfat, base + nfat + ndif))
    fat.extend([DIFSECT] * ndif)
    while len(fat) % per:
        fat.append(FREE)
    fat_blob = b"".join(struct.pack("<I", x) for x in fat)
    for i in range(nfat):
        sectors.append(fat_blob[i * SECT:(i + 1) * SECT])
    difat = fat_ids[:109] + [FREE] * (109 - min(109, len(fat_ids)))
    rest = fat_ids[109:]
    for j, did in enumerate(dif_ids):
        chunk = rest[j * (per - 1):(j + 1) * (per - 1)]
        chunk += [FREE] * (per - 1 - len(chunk))
        nxt = dif_ids[j + 1] if j + 1 < len(dif_ids) else ENDCHAIN
        sectors.append(struct.pack("<%dI" % per, *(chunk + [nxt])))

    hdr = bytearray(512)
    hdr[:8] = SIG
    struct.pack_into("<HHHHH", hdr, 24, 0x003E, 3, 0xFFFE, 9, 6)
    struct.pack_into("<I", hdr, 40, 0)
    struct.pack_into("<IIIIIIII", hdr, 44, nfat, dir_start, 0, CUTOFF, mf_start, n_mf,
                     dif_ids[0] if dif_ids else ENDCHAIN, len(dif_ids))
    struct.pack_into("<109I", hdr, 76, *difat)
    return bytes(hdr) + b"".join(sectors)
