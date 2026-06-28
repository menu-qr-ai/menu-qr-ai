from io import BytesIO

import qrcode


def build_qr_png_bytes(url: str) -> bytes:
    image = qrcode.make(url)
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()

