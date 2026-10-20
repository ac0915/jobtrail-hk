"""Job import previews: JobsDB link fetch, or paste text (Indeed / others)."""
import zlib, base64, pathlib
_here = pathlib.Path(__file__).resolve().parent
_b64 = "".join((_here / f"_imports_part{i}.b64").read_text() for i in range(6))
exec(zlib.decompress(base64.b64decode(_b64)).decode())
