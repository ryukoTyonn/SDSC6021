"""Archive every HTTP response without changing the frozen experimental runner."""
import io, json, hashlib, time, sys
from pathlib import Path
from urllib import request, error
import run_formal
ROOT = Path(__file__).resolve().parent
original = request.urlopen
counter = 0
class Response(io.BytesIO):
    def __init__(self, data, source):
        super().__init__(data)
        self.headers = source.headers
        self.status = getattr(source, 'status', None)
    def getcode(self): return self.status

def audited(req, *args, **kwargs):
    global counter
    counter += 1
    prefix = ROOT/'audit'/f'{time.time_ns()}_{counter:03d}'
    payload = req.data or b''
    # Deliberately exclude authentication headers.
    prefix.with_suffix('.request.json').write_bytes(payload)
    meta = {'url': req.full_url, 'started_at': time.time(), 'request_sha256': hashlib.sha256(payload).hexdigest()}
    try:
        with original(req, *args, **kwargs) as response:
            data = response.read()
            meta['http_status'] = response.status
            prefix.with_suffix('.response.bin').write_bytes(data)
            return Response(data, response)
    except error.HTTPError as exc:
        data = exc.read()
        prefix.with_suffix('.response.bin').write_bytes(data)
        meta['http_status'] = exc.code
        raise error.HTTPError(exc.url, exc.code, exc.msg, exc.headers, io.BytesIO(data))
    except Exception as exc:
        meta['error'] = str(exc)
        raise
    finally:
        meta['finished_at'] = time.time()
        prefix.with_suffix('.meta.json').write_text(json.dumps(meta, ensure_ascii=False, indent=2))

if __name__ == '__main__':
    request.urlopen = audited
    run_formal.main()
