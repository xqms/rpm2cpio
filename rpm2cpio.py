#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Lightweight RPM to CPIO converter.
# Copyright © 2008-2017 Rudá Moura. All rights reserved.
#

'''Extract cpio archive from RPM package.

rpm2cpio converts the RPM on standard input or first parameter to a CPIO archive on standard output.

Usage:
rpm2cpio < adjtimex-1.20-2.1.i386.rpm  | cpio -it
./sbin/adjtimex
./usr/share/doc/adjtimex-1.20
./usr/share/doc/adjtimex-1.20/COPYING
./usr/share/doc/adjtimex-1.20/COPYRIGHT
./usr/share/doc/adjtimex-1.20/README
./usr/share/man/man8/adjtimex.8.gz
133 blocks
'''

import sys
import gzip
import subprocess

from io import BytesIO

HAS_LZMA_MODULE = True
try:
    import lzma
except ImportError:
    try:
        import backports.lzma as lzma
    except ImportError:
        HAS_LZMA_MODULE = False


RPM_MAGIC = b'\xed\xab\xee\xdb'


def gzip_decompress(data):
    gzstream = BytesIO(data)
    gzipper = gzip.GzipFile(fileobj=gzstream)
    data = gzipper.read()
    return data


def xz_decompress(data):
    if HAS_LZMA_MODULE:
        return lzma.decompress(data)
    unxz = subprocess.Popen(['unxz'], stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    data = unxz.communicate(input=data)[0]
    return data


def zstd_decompress(data):
    unzstd = subprocess.Popen(['unzstd'], stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    data = unzstd.communicate(input=data)[0]
    return data


def bzip2_decompress(data):
    bunzip2 = subprocess.Popen(
        ['bunzip2'], stdin=subprocess.PIPE, stdout=subprocess.PIPE
    )
    data = bunzip2.communicate(input=data)[0]
    return data


def is_rpm(reader):
    return reader.read(4) == RPM_MAGIC

def b2i(data, order='big'):
    """
    Converts bytes to integer
    """
    return int.from_bytes(data, order)


def b2s(fileobj, encoding='utf-8'):
    """
    Reads until \x00
    """
    chars = list()
    while True:
        c = fileobj.read(1)
        if c == b'\x00':
            return "".join(chars)
        chars.append(c.decode(encoding))


def extract_cpio(reader):
    rpm_major, rpm_minor = reader.read(1), reader.read(1)
    rpm_type = reader.read(2)
    rpm_arch = reader.read(2)
    rpm_name = reader.read(66)
    rpm_os = reader.read(2)
    rpm_sig_type = reader.read(2)
    rpm_reserved = reader.read(16)
    # SIGNATURE
    rpm_sig_magic = reader.read(3)
    rpm_sig_version = reader.read(1)

    assert rpm_sig_magic == b'\216\255\350', f'Wrong RPM sig magic ({rpm_sig_magic})'
    assert rpm_sig_version == b'\x01', f'Wrong RPM sig version ({rpm_sig_version})'

    rpm_sig_reserved = reader.read(4)
    rpm_sig_idx_len = b2i(reader.read(4))
    rpm_sig_data_len = b2i(reader.read(4))
    ## Skip signature parsing
    reader.read(rpm_sig_idx_len * 16 + rpm_sig_data_len)

    # Skip to next 8 byte boundary
    if reader.tell() % 8 != 0:
        reader.read(8 - reader.tell() % 8)

    # HEADER
    rpm_header_magic = reader.read(3)
    rpm_header_version = reader.read(1)
    rpm_header_reserved = reader.read(4)
    rpm_header_idx_len = reader.read(4)
    rpm_header_data_len = reader.read(4)
    rpm_header_data_offset_base = reader.tell() + b2i(rpm_header_idx_len) * 16

    assert rpm_header_magic == b'\216\255\350', f'Wrong RPM header magic ({rpm_header_magic})'
    assert rpm_header_version == b'\x01'

    rpm_tag_payloadcompressor = None
    for tag in range(b2i(rpm_header_idx_len) - 1):
        tag_id = b2i(reader.read(4))
        tag_data_type = b2i(reader.read(4))
        tag_offset = b2i(reader.read(4))
        tag_data_count = b2i(reader.read(4))
        if tag_id == 1125:
            pos_backup = reader.tell()
            reader.seek(rpm_header_data_offset_base + tag_offset)
            rpm_tag_payloadcompressor = b2s(reader)
            reader.seek(pos_backup)

    reader.seek(rpm_header_data_offset_base + b2i(rpm_header_data_len))
    compressed_data = reader.read()

    if rpm_tag_payloadcompressor is None:
        return compressed_data  # is actually not compressed

    if rpm_tag_payloadcompressor == 'lzma' or rpm_tag_payloadcompressor == 'xz':
        return xz_decompress(compressed_data)
    elif rpm_tag_payloadcompressor == 'gzip':
        return gzip_decompress(compressed_data)
    elif rpm_tag_payloadcompressor == 'zstd':
        return zstd_decompress(compressed_data)
    elif rpm_tag_payloadcompressor == 'bzip2':
        return bzip2_decompress(compressed_data)

    return None

def rpm2cpio():
    buffer = sys.stdin.buffer.read()
    reader = BytesIO(buffer)
    writer = sys.stdout.buffer

    if not is_rpm(reader):
        raise IOError('the input is not a RPM package')
    cpio = extract_cpio(reader)
    if cpio is None:
        raise IOError('could not find compressed cpio archive')
    writer.write(cpio)

if __name__ == '__main__':
    rpm2cpio()
