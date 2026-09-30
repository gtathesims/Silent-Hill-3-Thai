"""Verified resource replacements for the approved PC picture archive."""
import base64
import hashlib
import json
import struct
import zlib
from .adapter import INSTALLER_ROOT, sha256_file

def payload():
    path = INSTALLER_ROOT/'payload/silent_hill_3_pic.json'
    manifest = json.loads((INSTALLER_ROOT/'payload/manifest.json').read_text(encoding='utf-8'))
    declaration = next(x for x in manifest['operations'] if x['target']=='data/pic.arc')
    if sha256_file(path) != declaration['payload']['sha256']:
        raise ValueError('Picture payload checksum mismatch')
    return json.loads(path.read_text(encoding='utf-8'))

def validate_pic(path):
    if sha256_file(path) != payload()['result_sha256']:
        raise ValueError('Picture archive result checksum mismatch')

def build_pic(source, output):
    spec = payload()
    if sha256_file(source) != spec['source_sha256']:
        raise ValueError('Unsupported original picture archive')
    data = bytearray(source.read_bytes())
    count = struct.unpack_from('<I', data, 4)[0]
    seen = set()
    for item in spec['entries']:
        index = item['index']
        if index in seen or not 0 <= index < count:
            raise ValueError('Invalid picture selector')
        seen.add(index)
        offset, _, size, _ = struct.unpack_from('<4I',data,16+index*16)
        if (offset,size) != (item['offset'],item['size']) or offset+size>len(data):
            raise ValueError('Picture resource layout mismatch')
        original = data[offset:offset+size]
        if hashlib.sha256(original).hexdigest().upper()!=item['source_sha256']:
            raise ValueError('Picture resource fingerprint mismatch')
        replacement = zlib.decompress(base64.b64decode(item['data'],validate=True))
        if len(replacement)!=size or hashlib.sha256(replacement).hexdigest().upper()!=item['result_sha256']:
            raise ValueError('Picture replacement integrity mismatch')
        data[offset:offset+size]=replacement
    if hashlib.sha256(data).hexdigest().upper()!=spec['result_sha256']:
        raise ValueError('Picture candidate mismatch')
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_bytes(data)

def inspect_pic(path, config):
    if not path.is_file():
        return dict(path=str(path),state='missing',compatible=False)
    digest = sha256_file(path)
    state = 'unsupported'
    if digest==config['known_original_sha256']:
        state='known-original'
    elif digest==config['known_patched_sha256']:
        state='known-patched'
    return dict(path=str(path),sha256=digest,state=state,compatible=state!='unsupported')
