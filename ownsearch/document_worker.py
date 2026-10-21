"""Isolated bounded PDF/Office/gzip extraction; never executes document scripts."""
import json
import sys
from dataclasses import asdict

def main():
    try:
        import resource
        resource.setrlimit(resource.RLIMIT_AS, (512 * 1024**2, 512 * 1024**2))
        resource.setrlimit(resource.RLIMIT_CPU, (2, 2))
        resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))
    except ImportError:
        pass
    from .config import Settings
    from .extract import extract
    data = sys.stdin.buffer.read(2_000_001)
    if len(data) > 2_000_000:
        raise ValueError('Document exceeds extraction limit')
    ext = extract(data, sys.argv[1], sys.argv[2], Settings(ocr='off'))
    ext.text = ext.text[:60_000]
    ext.metadata = {k: v for k, v in ext.metadata.items() if isinstance(v, (str, int, float, bool))}
    print(json.dumps(asdict(ext)))

if __name__ == '__main__':
    main()
