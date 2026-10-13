"""OCR hook. Uses the locally installed open-source Tesseract binary when present (free, offline);
disabled cleanly when it is missing or ``ocr = "off"``. No cloud OCR is ever used."""
import os
import shutil
import subprocess
import tempfile

_AVAILABLE = {}


def ocr_available(settings):
    if settings.ocr == "off":
        return False
    cmd = settings.tesseract_cmd
    if cmd not in _AVAILABLE:
        _AVAILABLE[cmd] = shutil.which(cmd) is not None
    return _AVAILABLE[cmd]


def ocr_image(data, suffix, settings):
    """-> (text, status). status: ok | unavailable | failed: ..."""
    if not ocr_available(settings):
        return "", "unavailable"
    fd, path = tempfile.mkstemp(suffix=suffix, prefix="ownsearch-ocr-")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        proc = subprocess.run([settings.tesseract_cmd, path, "stdout", "-l", settings.ocr_lang, "--psm", "3"],
                              capture_output=True, timeout=settings.ocr_timeout, check=False)
        if proc.returncode != 0:
            return "", "failed: " + proc.stderr.decode("utf-8", "replace").strip()[-200:]
        return proc.stdout.decode("utf-8", "replace"), "ok"
    except subprocess.TimeoutExpired:
        return "", "failed: timeout"
    except OSError as e:
        return "", f"failed: {e}"
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
