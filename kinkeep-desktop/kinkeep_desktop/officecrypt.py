"""Password encryption of Office Open XML files (.xlsx) per MS-OFFCRYPTO, so that Excel,
LibreOffice and other spreadsheet programs open the file with the password, no KinKeep needed.

Modes
  agile     AES-256-CBC, SHA-512, 100,000 spin count, HMAC-SHA512 integrity (Office 2010+). Default.
  standard  AES-128-ECB, SHA-1, 50,000 iterations (Office 2007 style). Same layout LibreOffice writes.
            Weaker; offered only as a compatibility fallback.

Pure Python on top of `cryptography`. Nothing is written to disk by this module.
"""
from __future__ import annotations
import base64
import hashlib
import hmac
import os
import re
import struct
from xml.etree import ElementTree as ET

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from . import cfb

AGILE_SPIN = 100_000
STD_SPIN = 50_000
_BK_VERIFIER_INPUT = bytes.fromhex("fea7d2763b4b9e79")
_BK_VERIFIER_VALUE = bytes.fromhex("d7aa0f6d3061344e")
_BK_KEY = bytes.fromhex("146e0be7abacd0d6")
_BK_HMAC_KEY = bytes.fromhex("5fb2ad010cb9e1f6")
_BK_HMAC_VALUE = bytes.fromhex("a0677f02b22c8433")
NS_ENC = "http://schemas.microsoft.com/office/2006/encryption"
NS_P = "http://schemas.microsoft.com/office/2006/keyEncryptor/password"


class WrongPassword(Exception):
    pass


class FormatError(Exception):
    pass


def is_encrypted(data: bytes) -> bool:
    return data[:8] == cfb.SIG


def _cbc(key, iv, data, enc):
    c = Cipher(algorithms.AES(key), modes.CBC(iv))
    x = c.encryptor() if enc else c.decryptor()
    return x.update(data) + x.finalize()


def _ecb(key, data, enc):
    c = Cipher(algorithms.AES(key), modes.ECB())
    x = c.encryptor() if enc else c.decryptor()
    return x.update(data) + x.finalize()


def _pad16(b: bytes) -> bytes:
    return b + b"\0" * (-len(b) % 16)


def _fit(b: bytes, n: int, pad=0x36) -> bytes:
    return b[:n] if len(b) >= n else b + bytes([pad]) * (n - len(b))


def _pw(password: str) -> bytes:
    return password.encode("utf-16-le")


# ----------------------------------------------------------------------------- agile
def _agile_hash(password, salt, spin, hname="sha512"):
    h = hashlib.new(hname, salt + _pw(password)).digest()
    for i in range(spin):
        h = hashlib.new(hname, struct.pack("<I", i) + h).digest()
    return h


def _agile_key(h, block, keybits, hname="sha512"):
    return _fit(hashlib.new(hname, h + block).digest(), keybits // 8)


def _b64(b):
    return base64.b64encode(b).decode()


def _encrypt_agile(plain: bytes, password: str, spin=AGILE_SPIN) -> dict[str, bytes]:
    key_salt, ke_salt, ver_salt = os.urandom(16), os.urandom(16), os.urandom(16)
    inter = os.urandom(32)
    h = _agile_hash(password, ke_salt, spin)
    e_vin = _cbc(_agile_key(h, _BK_VERIFIER_INPUT, 256), ke_salt, ver_salt, True)
    e_vval = _cbc(_agile_key(h, _BK_VERIFIER_VALUE, 256), ke_salt, hashlib.sha512(ver_salt).digest(), True)
    e_key = _cbc(_agile_key(h, _BK_KEY, 256), ke_salt, inter, True)
    # data
    out = bytearray(struct.pack("<Q", len(plain)))
    for i in range(0, max(len(plain), 1), 4096):
        seg = _pad16(plain[i:i + 4096])
        iv = hashlib.sha512(key_salt + struct.pack("<I", i // 4096)).digest()[:16]
        out += _cbc(inter, iv, seg, True)
    pkg = bytes(out)
    hkey = os.urandom(64)
    hval = hmac.new(hkey, pkg, hashlib.sha512).digest()
    e_hkey = _cbc(inter, hashlib.sha512(key_salt + _BK_HMAC_KEY).digest()[:16], hkey, True)
    e_hval = _cbc(inter, hashlib.sha512(key_salt + _BK_HMAC_VALUE).digest()[:16], hval, True)
    xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\r\n'
        f'<encryption xmlns="{NS_ENC}" xmlns:p="{NS_P}" '
        'xmlns:c="http://schemas.microsoft.com/office/2006/keyEncryptor/certificate">'
        f'<keyData saltSize="16" blockSize="16" keyBits="256" hashSize="64" cipherAlgorithm="AES" '
        f'cipherChaining="ChainingModeCBC" hashAlgorithm="SHA512" saltValue="{_b64(key_salt)}"/>'
        f'<dataIntegrity encryptedHmacKey="{_b64(e_hkey)}" encryptedHmacValue="{_b64(e_hval)}"/>'
        '<keyEncryptors><keyEncryptor uri="http://schemas.microsoft.com/office/2006/keyEncryptor/password">'
        f'<p:encryptedKey spinCount="{spin}" saltSize="16" blockSize="16" keyBits="256" hashSize="64" '
        'cipherAlgorithm="AES" cipherChaining="ChainingModeCBC" hashAlgorithm="SHA512" '
        f'saltValue="{_b64(ke_salt)}" encryptedVerifierHashInput="{_b64(e_vin)}" '
        f'encryptedVerifierHashValue="{_b64(e_vval)}" encryptedKeyValue="{_b64(e_key)}"/>'
        '</keyEncryptor></keyEncryptors></encryption>'
    )
    info = struct.pack("<HHI", 4, 4, 0x40) + xml.encode("utf-8")
    return {"EncryptionInfo": info, "EncryptedPackage": pkg, **_dataspaces()}


def _lpp4(s: str) -> bytes:
    b = s.encode("utf-16-le")
    return struct.pack("<I", len(b)) + b + b"\0" * (-len(b) % 4)


def _dataspaces() -> dict[str, bytes]:
    ver = struct.pack("<HH", 1, 0)
    version = _lpp4("Microsoft.Container.DataSpaces") + ver + ver + ver
    entry = struct.pack("<II", 0, 0)  # placeholder, rebuilt below
    comp = struct.pack("<I", 0) + _lpp4("EncryptedPackage")
    body = struct.pack("<I", 1) + comp + _lpp4("StrongEncryptionDataSpace")
    entry = struct.pack("<I", 4 + len(body)) + body
    dsmap = struct.pack("<II", 8, 1) + entry
    dsdef = struct.pack("<II", 8, 1) + _lpp4("StrongEncryptionTransform")
    tid = _lpp4("{FF9A3F03-56EF-4613-BDD5-5A41C1D07246}")
    hdr = struct.pack("<II", 4 + 4 + len(tid), 1) + tid
    primary = hdr + _lpp4("Microsoft.Container.EncryptionTransform") + ver + ver + ver + struct.pack("<I", 0)
    return {
        "\x06DataSpaces/Version": version,
        "\x06DataSpaces/DataSpaceMap": dsmap,
        "\x06DataSpaces/DataSpaceInfo/StrongEncryptionDataSpace": dsdef,
        "\x06DataSpaces/TransformInfo/StrongEncryptionTransform/\x06Primary": primary,
    }


def _decrypt_agile(info: bytes, pkg: bytes, password: str) -> bytes:
    try:
        root = ET.fromstring(info[8:].decode("utf-8-sig"))
    except Exception as e:  # pragma: no cover
        raise FormatError("bad encryption descriptor") from e
    kd = root.find(f"{{{NS_ENC}}}keyData")
    ek = root.find(f".//{{{NS_P}}}encryptedKey")
    if kd is None or ek is None:
        raise FormatError("unsupported key encryptor")
    hname = ek.get("hashAlgorithm", "SHA512").lower().replace("-", "")
    if ek.get("cipherAlgorithm") != "AES" or ek.get("cipherChaining") != "ChainingModeCBC" or hname not in ("sha512", "sha256", "sha384", "sha1"):
        raise FormatError("unsupported cipher")
    spin = int(ek.get("spinCount"))
    if spin > 10_000_000:
        raise FormatError("unreasonable spin count")
    bits = int(ek.get("keyBits"))
    salt = base64.b64decode(ek.get("saltValue"))
    h = _agile_hash(password, salt, spin, hname)
    vin = _cbc(_agile_key(h, _BK_VERIFIER_INPUT, bits, hname), salt, base64.b64decode(ek.get("encryptedVerifierHashInput")), False)
    vval = _cbc(_agile_key(h, _BK_VERIFIER_VALUE, bits, hname), salt, base64.b64decode(ek.get("encryptedVerifierHashValue")), False)
    if not hmac.compare_digest(hashlib.new(hname, vin).digest(), vval[:hashlib.new(hname).digest_size]):
        raise WrongPassword()
    inter = _cbc(_agile_key(h, _BK_KEY, bits, hname), salt, base64.b64decode(ek.get("encryptedKeyValue")), False)[:bits // 8]
    ksalt = base64.b64decode(kd.get("saltValue"))
    khash = kd.get("hashAlgorithm", "SHA512").lower().replace("-", "")
    di = root.find(f"{{{NS_ENC}}}dataIntegrity")
    if di is not None:
        hk = _cbc(inter, hashlib.new(khash, ksalt + _BK_HMAC_KEY).digest()[:16], base64.b64decode(di.get("encryptedHmacKey")), False)
        hv = _cbc(inter, hashlib.new(khash, ksalt + _BK_HMAC_VALUE).digest()[:16], base64.b64decode(di.get("encryptedHmacValue")), False)
        dsz = hashlib.new(khash).digest_size
        if not hmac.compare_digest(hmac.new(hk[:dsz], pkg, khash).digest(), hv[:dsz]):
            raise FormatError("integrity check failed: the file was modified or damaged")
    size = struct.unpack_from("<Q", pkg, 0)[0]
    out = bytearray()
    body = pkg[8:]
    for i in range(0, len(body), 4096):
        iv = hashlib.new(khash, ksalt + struct.pack("<I", i // 4096)).digest()[:16]
        out += _cbc(inter, iv, body[i:i + 4096], False)
    return bytes(out[:size])


# ----------------------------------------------------------------------------- standard
def _std_key(password, salt, keybits):
    h = hashlib.sha1(salt + _pw(password)).digest()
    for i in range(STD_SPIN):
        h = hashlib.sha1(struct.pack("<I", i) + h).digest()
    h = hashlib.sha1(h + struct.pack("<I", 0)).digest()
    b1 = hashlib.sha1(bytes((0x36 ^ (h[i] if i < len(h) else 0)) for i in range(64))).digest()
    b2 = hashlib.sha1(bytes((0x5C ^ (h[i] if i < len(h) else 0)) for i in range(64))).digest()
    return (b1 + b2)[:keybits // 8]


def _encrypt_standard(plain: bytes, password: str) -> dict[str, bytes]:
    salt, verifier = os.urandom(16), os.urandom(16)
    key = _std_key(password, salt, 128)
    csp = "Microsoft Enhanced RSA and AES Cryptographic Provider".encode("utf-16-le") + b"\0\0"
    header = struct.pack("<IIIIIIII", 0x24, 0, 0x660E, 0x8004, 128, 0x18, 0, 0) + csp
    ver = struct.pack("<I", 16) + salt + _ecb(key, verifier, True) + struct.pack("<I", 20) + \
        _ecb(key, _pad16(hashlib.sha1(verifier).digest()), True)
    info = struct.pack("<HHII", 3, 2, 0x24, len(header)) + header + ver
    pkg = struct.pack("<Q", len(plain)) + _ecb(key, _pad16(plain), True)
    return {"EncryptionInfo": info, "EncryptedPackage": pkg}


def _decrypt_standard(info: bytes, pkg: bytes, password: str) -> bytes:
    hsize = struct.unpack_from("<I", info, 8)[0]
    flags, _, alg, hid, kbits, _, _, _ = struct.unpack_from("<IIIIIIII", info, 12)
    if alg != 0x660E and alg not in (0x660F, 0x6610):
        raise FormatError("unsupported cipher (RC4 files are not supported)")
    p = 12 + hsize
    ssz = struct.unpack_from("<I", info, p)[0]
    salt = info[p + 4:p + 4 + ssz]
    ev = info[p + 4 + ssz:p + 4 + ssz + 16]
    evh = info[p + 4 + ssz + 20:p + 4 + ssz + 52]
    key = _std_key(password, salt, kbits)
    ver = _ecb(key, ev, False)
    got = _ecb(key, evh, False)[:20]
    if not hmac.compare_digest(hashlib.sha1(ver).digest(), got):
        raise WrongPassword()
    size = struct.unpack_from("<Q", pkg, 0)[0]
    return _ecb(key, pkg[8:], False)[:size]


# ----------------------------------------------------------------------------- public
def encrypt(plain: bytes, password: str, mode: str = "agile") -> bytes:
    if not password:
        raise ValueError("password required")
    streams = _encrypt_agile(plain, password) if mode == "agile" else _encrypt_standard(plain, password)
    return cfb.write_streams(streams)


def decrypt(data: bytes, password: str) -> bytes:
    try:
        s = cfb.read_streams(data)
    except cfb.CfbError as e:
        raise FormatError(str(e)) from e
    if "EncryptionInfo" not in s or "EncryptedPackage" not in s:
        raise FormatError("not an encrypted Office file")
    info = s["EncryptionInfo"]
    major, minor = struct.unpack_from("<HH", info, 0)
    if (major, minor) == (4, 4):
        return _decrypt_agile(info, s["EncryptedPackage"], password)
    if major in (2, 3, 4) and minor == 2:
        return _decrypt_standard(info, s["EncryptedPackage"], password)
    raise FormatError("unsupported encryption version %d.%d" % (major, minor))
