"""Pure Python implementation of Firefox cache extractor."""

import struct
from pathlib import Path

# constants
CHUNK_SIZE = 256 * 1024
HASH_SIZE = 20
MAX_ALLOC = 100 * 1024 * 1024
MAX_KEY_SIZE = 65536


# HttpHeader
class HttpHeader:
    
    headers: dict
    status_code: int
    status_source: str
    status_message: str
    protocol: str

    def __init__(self, src: str) -> None:
        self.headers = {}
        self.status_code = 0
        self.status_source = ""
        self.status_message = ""
        self.protocol = ""

        if not src:
            return

        lines = src.split('\n')
        if not lines:
            return

        # status
        self.status_source = lines[0].strip()
        status_parts = self.status_source.split(' ')
        if len(status_parts) >= 2:
            self.protocol = status_parts[0]
            try:
                self.status_code = int(status_parts[1])
            except (ValueError, IndexError):
                self.status_code = 0
            if len(status_parts) > 2:
                self.status_message = ' '.join(status_parts[2:])

        # headers
        for line in lines[1:]:
            if not line:
                continue
            idx = line.find(':')
            if idx != -1:
                k = line[:idx].strip().lower()
                v = line[idx+1:].strip()
                if k:
                    self.headers[k] = v


# FirefoxCacheEntry
class FirefoxCacheEntry:
    
    file_path: str
    key: str
    meta_start: int
    meta_end: int
    map_start: int
    fetch_count: int
    last_fetch: int
    last_modified: int
    frequency: int
    expiration: int
    flags: int
    _map_cache: object

    def __init__(self, path) -> None:
        path_str = str(path)
        self.file_path = path_str
        self.key = ""
        self.meta_start = 0
        self.meta_end = 0
        self.map_start = 0
        self.fetch_count = 0
        self.last_fetch = 0
        self.last_modified = 0
        self.frequency = 0
        self.expiration = 0
        self.flags = 0
        self._map_cache = None

        self._parse_key_only(path_str)

    def _parse_key_only(self, path: str) -> None:
        with open(path, 'rb') as f:
            f.seek(0, 2)
            file_size = f.tell()
            if file_size < 8:
                raise ValueError("file too small")

            self.meta_end = file_size - 4
            f.seek(-4, 2)
            r = f.read(4)
            # meta start
            self.meta_start = struct.unpack('>I', r)[0]
            if self.meta_start > self.meta_end:
                raise ValueError("invalid meta_start")

            numHashChunks = (self.meta_start + CHUNK_SIZE - 1) // CHUNK_SIZE
            meta_header_offset = self.meta_start + 4 + numHashChunks * 2

            # meta data
            if meta_header_offset + 32 > file_size:
                raise ValueError("metadata header outside file")
            f.seek(meta_header_offset)
            r = f.read(32)
            if len(r) >= 32:
                vals = struct.unpack('>IIIIIIII', r)
                self.fetch_count = vals[1]
                self.last_fetch = vals[2]
                self.last_modified = vals[3]
                self.frequency = vals[4]
                self.expiration = vals[5]
                key_size = vals[6]
            else:
                key_size = 0
            
            # key
            if key_size > 0 and key_size < MAX_KEY_SIZE:
                keylen = key_size
                if keylen > MAX_ALLOC:
                    raise MemoryError()
                if meta_header_offset + 32 + keylen > file_size:
                    raise ValueError("key outside file")
                
                f.seek(meta_header_offset + 32)
                keybuf = f.read(keylen)
                if len(keybuf) > 0:
                    actual = len(keybuf)
                    for i in range(actual):
                        if keybuf[i:i+1] == b'\x00':
                            actual = i
                            break
                    
                    key_str = keybuf[:actual].decode('utf-8', errors='replace')
                    idx = key_str.find(':')
                    if idx != -1:
                        self.key = key_str[idx+1:]
                    else:
                        self.key = key_str
            
            self.map_start = self.meta_start + key_size + 1
    
    def load_map(self) -> dict:
        if self._map_cache is not None:
            return self._map_cache

        result = {}
        try:
            if self.map_start >= self.meta_end:
                self._add_metadata_to_result(result)
                self._map_cache = result
                return result

            length = self.meta_end - self.map_start
            if length == 0:
                self._add_metadata_to_result(result)
                self._map_cache = result
                return result

            with open(self.file_path, 'rb') as f:
                f.seek(self.map_start)
                buf = f.read(length)
            
            if len(buf) <= 0:
                self._add_metadata_to_result(result)
                self._map_cache = result
                return result
            
            ptr = 0
            while ptr < len(buf):
                key_start = ptr
                next_null = buf.find(b'\x00', ptr)
                if next_null == -1:
                    break
                klen = next_null - ptr
                ptr = next_null + 1
                
                if ptr >= len(buf):
                    break
                
                next_null = buf.find(b'\x00', ptr)
                if next_null == -1:
                    break
                vlen = next_null - ptr
                
                if klen > 0 and vlen > 0:
                    try:
                        kstr = buf[key_start:key_start+klen].decode('utf-8', errors='ignore')
                    except Exception:
                        kstr = None
                    try:
                        vstr = buf[ptr:ptr+vlen].decode('utf-8', errors='ignore')
                    except Exception:
                        vstr = None
                    if kstr is not None and vstr is not None:
                        try:
                            result[kstr] = vstr
                        except Exception:
                            pass
                ptr = next_null + 1
            
            self._add_metadata_to_result(result)
            self._map_cache = result
            return result
        except Exception:
            self._add_metadata_to_result(result)
            self._map_cache = result
            return result
    
    def _add_metadata_to_result(self, result: dict) -> None:
        if self.fetch_count > 0:
            result['fetch-count'] = str(self.fetch_count)
        if self.last_fetch > 0:
            result['last-fetch'] = str(self.last_fetch)
        if self.last_modified > 0:
            result['last-modified'] = str(self.last_modified)
        if self.frequency > 0:
            result['frequency'] = str(self.frequency)
        if self.expiration > 0:
            result['expiration'] = str(self.expiration)
        if self.flags > 0:
            result['flags'] = str(self.flags)

    def get_data(self) -> bytes:

        if self.meta_start == 0:
            return b''

        if self.meta_start > MAX_ALLOC:
            raise MemoryError("refusing huge allocation")
        
        with open(self.file_path, 'rb') as f:
            f.seek(0)
            result = f.read(self.meta_start)
        
        if len(result) <= 0:
            return b''
        
        return result
    
    def save(self, path: str) -> bool:
        data = self.get_data()
        if not data:
            return False
        try:
            with open(path, 'wb') as f:
                f.write(data)
            return True
        except Exception as e:
            raise RuntimeError(f"Failed to save: {e}")

    def get_header(self) -> 'HttpHeader':
        try:
            meta_map = self.load_map()
            header_str = meta_map.get('response-head', '')
            return HttpHeader(header_str)
        except Exception:
            return HttpHeader("HTTP/1.1 200 OK\r\n")


# FirefoxCacheIndex
class FirefoxCacheIndex:
    
    header: dict
    records: list
    
    def __init__(self, path: str | None = None) -> None:
        self.header = {}
        self.records = []
        if path:
            self._read_index(str(path))

    def _read_index(self, path: str) -> None:
        index_size = Path(path).stat().st_size
        try:
            with open(path, 'rb') as f:
                header_data = f.read(12)
                if len(header_data) == 12:
                    (
                        self.header['mVersion'],
                        self.header['mTimeStamp'],
                        self.header['mIsDirty']
                    ) = struct.unpack('>III', header_data)
                
                while True:
                    record_data = f.read(36)
                    if len(record_data) < 36:
                        break
                    
                    hash_bytes = record_data[:HASH_SIZE]
                    hash_str = ''.join(f'{b:02X}' for b in hash_bytes)
                    frequency = struct.unpack('>i', record_data[20:24])[0]
                    expires = struct.unpack('>i', record_data[24:28])[0]
                    app_id = struct.unpack('>i', record_data[28:32])[0]
                    flags = struct.unpack('>B', record_data[32:33])[0]
                    size = struct.unpack('>I', b'\x00'+record_data[33:36])[0]
                    self.records.append({
                        'hash': hash_str,
                        'frequency': frequency,
                        'expires': expires,
                        'appId': app_id,
                        'flags': flags,
                        'size': size
                    })
        except Exception as e:
            raise RuntimeError(f"Error reading index: {e}")


# FirefoxCache
class FirefoxCache:
    
    records: list
    index: object

    def __init__(self, cache2_dir: str) -> None:
        self.records = []
        self.index = None

        cache_path = Path(cache2_dir)
        index_path = cache_path / "index"
        entries_path = cache_path / "entries"

        if index_path.exists():
            self.index = FirefoxCacheIndex(str(index_path))

        if entries_path.exists():
            for entry_file in entries_path.iterdir():
                if entry_file.is_file():
                    try:
                        entry = FirefoxCacheEntry(str(entry_file))
                        self.records.append(entry)
                    except Exception as e:
                        raise RuntimeError(f"Error loading entry {entry_file.name}: {e}")

    def find(self, key: str) -> 'FirefoxCacheEntry':
        for entry in self.records:
            if entry.key == key:
                return entry
        raise KeyError(f"Key not found: {key}")

    def find_save(self, key: str, path: str) -> None:
        entry = self.find(key)
        entry.save(path)

    def keys(self) -> list:
        return [entry.key for entry in self.records]
