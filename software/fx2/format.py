import os
import io
import re


__all__ = ['input_data', 'output_data']


def autodetect(file):
    """
    Autodetect file format based on properties of a given file object.

    Returns `"ihex"` for `.hex`, `.ihex` and `.ihx` file extensions,
    `"bin"` for `.bin` file extension, `"hex"` if ``file`` is a TTY,
    and raises :class:`ValueError` otherwise.
    """
    basename, extname = os.path.splitext(file.name)
    if extname in [".hex", ".ihex", ".ihx"]:
        return "ihex"
    elif extname in [".bin"]:
        return "bin"
    elif file.isatty():
        return "hex"
    else:
        raise ValueError("Specify file format explicitly")


def output_data(file, data, fmt="auto", offset=0):
    """
    Write Intel HEX, hexadecimal, or binary ``data`` to ``file``.

    :param offset:
        Offset the data by specified amount of bytes.
    :param fmt:
        ``"ihex"`` for Intel HEX, ``"hex"`` for hexadecimal, ``"bin"`` for binary,
        or ``"auto"`` for autodetection via :func:`autodetect`.
    """

    if isinstance(file, io.TextIOWrapper):
        file = file.buffer

    if fmt == "auto":
        fmt = autodetect(file)

    if fmt == "bin":
        file.write(data)

    elif fmt == "hex":
        n = 0
        for n, byte in enumerate(data):
            file.write("{:02x}".format(byte).encode())
            if n > 0 and n % 16 == 15:
                file.write(b"\n")
            elif n > 0 and n % 8 == 7:
                file.write(b"  ")
            else:
                file.write(b" ")
        if n % 16 != 15:
            file.write(b"\n")

    elif fmt == "ihex":
        pos = 0
        while pos < len(data):
            recoff  = offset + pos
            recdata = data[pos:pos + 0x10]
            record  = [
                len(recdata),
                (recoff >> 8) & 0xff,
                (recoff >> 0) & 0xff,
                0x00,
                *list(recdata)
            ]
            record.append((~sum(record) + 1) & 0xff)
            file.write(b":")
            file.write(bytes(record).hex().encode())
            file.write(b"\n")
            pos += len(recdata)
        file.write(b":00000001ff\n")


def input_data(file_or_data, fmt="auto", offset=0):
    """
    Read Intel HEX, hexadecimal, or binary data from ``file_or_data``.
    If ``file_or_data`` is a string, it is treated as hexadecimal. Otherwise,
    the format is determined by the ``fmt`` argument.

    Raises :class:`ValueError` if the input data has invalid format.

    Returns a list of ``(address, data)`` chunks.

    :param offset:
        Offset the data by specified amount of bytes.
    :param fmt:
        ``"ihex"`` for Intel HEX, ``"hex"`` for hexadecimal, ``"bin"`` for binary,
        or ``"auto"`` for autodetection via :func:`autodetect`.
    """

    if isinstance(file_or_data, io.TextIOWrapper):
        file_or_data = file_or_data.buffer

    if isinstance(file_or_data, str):
        fmt = "hex"
        data = file_or_data.encode()
    else:
        data = file_or_data.read()

    if fmt == "auto":
        fmt = autodetect(file_or_data)

    if fmt == "bin":
        return [(offset, data)]

    elif fmt == "hex":
        try:
            hexdata = re.sub(r"\s*", "", data.decode())
            bindata = bytes.fromhex(hexdata)
        except ValueError as e:
            raise ValueError("Invalid hexadecimal data")
        return [(offset, bindata)]

    elif fmt == "ihex":
        RE_HDR = re.compile(rb":([0-9a-f]{8})", re.I)
        RE_WS  = re.compile(rb"\s*")

        bank_bias = 0  # Support Record Type 04
        resoff = 0
        resbuf = []
        res = []

        pos = 0
        while pos < len(data):
            match = RE_HDR.match(data, pos)
            if match is None:
                raise ValueError("Invalid record header at offset {}".format(pos))
            *rechdr, = bytes.fromhex(match.group(1).decode())
            reclen, recoffh, recoffl, rectype = rechdr

            recdatahex = data[match.end(0):match.end(0)+(reclen+1)*2]
            if len(recdatahex) < (reclen + 1) * 2:
                raise ValueError("Truncated record at offset {}".format(pos))
            try:
                *recdata, recsum = bytes.fromhex(recdatahex.decode())
            except ValueError:
                raise ValueError("Invalid record data at offset {}".format(pos))
            if sum(rechdr + recdata + [recsum]) & 0xff != 0:
                raise ValueError("Invalid record checksum at offset {}".format(pos))
            if rectype not in [0x00, 0x01, 0x04]:
                raise ValueError("Unknown record type at offset {}".format(pos))

            if rectype == 0x01:
                break
            elif rectype == 0x04:
                res.append((offset + resoff + bank_bias, resbuf))

                # If we switch banks, we know there is a discontinuity, so
                # make no assumption about previous position or buffer contents.
                resoff = 0
                resbuf = []
                bank_bias = ((recdata[0] << 8) | recdata[1]) << 16
            else:
                recoff = (recoffh << 8) | recoffl
                if resoff + len(resbuf) == recoff:
                    resbuf += recdata
                else:
                    if len(resbuf) > 0:
                        res.append((offset + resoff + bank_bias, resbuf))
                    resoff  = recoff
                    resbuf  = recdata

            match = RE_WS.match(data, match.end(0) + len(recdatahex))
            pos = match.end(0)

        # Handle last record that was seen before Record Type 0x01.
        if len(resbuf) > 0:
            res.append((offset + resoff + bank_bias, resbuf))

        return res