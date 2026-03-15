# cython: language_level=3

from pathlib import Path
from cpython.bytes cimport PyBytes_FromStringAndSize
from cpython.unicode cimport PyUnicode_DecodeUTF8

# constants
DEF CHUNK_SIZE = 256 * 1024
DEF HASH_SIZE = 20
DEF MAX_ALLOC = 100 * 1024 * 1024
DEF MAX_KEY_SIZE = 65536

# C external dependencies
cdef extern from "stdlib.h":
    ctypedef long ssize_t
    ctypedef long off_t
    void* malloc(size_t size)
    void free(void* ptr)

cdef extern from "string.h":
    void* memcpy(void* dest, const void* src, size_t n)
    void* memchr(const void* s, int c, size_t n)

cdef extern from "unistd.h":
    ssize_t pread(int fd, void* buf, size_t count, off_t offset)
    int close(int fd)

cdef extern from "fcntl.h":
    int c_open "open"(const char* path, int flags)
    int O_RDONLY
    int O_NOFOLLOW
    int O_CLOEXEC

cdef extern from "sys/stat.h":
    struct stat:
        off_t st_size
        int st_mode
    int fstat(int fd, stat* statbuf)

cdef extern from "sys/stat.h":
    int S_ISREG(int mode)

# utility function
cdef inline unsigned int _be32_from_buf(const unsigned char *p) nogil:
    return (<unsigned int>p[0] << 24) | (<unsigned int>p[1] << 16) | (<unsigned int>p[2] << 8) | (<unsigned int>p[3])

# HttpHeader
cdef class HttpHeader:
    
    cdef public dict headers
    cdef public int status_code
    cdef public str status_source
    cdef public str status_message
    cdef public str protocol

    def __init__(self, str src):
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
cdef class FirefoxCacheEntry:
    
    cdef public str file_path
    cdef public str key
    cdef public unsigned long meta_start
    cdef public unsigned long meta_end
    cdef public unsigned long map_start
    cdef public unsigned int fetch_count
    cdef public unsigned int last_fetch
    cdef public unsigned int last_modified
    cdef public unsigned int frequency
    cdef public unsigned int expiration
    cdef public unsigned int flags
    cdef object _map_cache

    def __init__(self, path):
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

    cdef void _parse_key_only(self, str path):
        cdef int fd = -1
        cdef stat st
        cdef unsigned long file_size
        cdef unsigned char *last4 = NULL
        cdef unsigned char *meta_buf = NULL
        cdef char *keybuf = NULL
        cdef ssize_t r
        cdef unsigned int key_size = 0
        cdef unsigned long numHashChunks
        cdef unsigned long meta_header_offset
        cdef Py_ssize_t keylen
        cdef Py_ssize_t actual
        cdef Py_ssize_t i
        cdef int idx
        cdef bytes pathb = path.encode('utf-8')

        try:
            fd = c_open(pathb, O_RDONLY | O_NOFOLLOW | O_CLOEXEC)
            if fd < 0:
                raise OSError("open failed")

            if fstat(fd, &st) != 0:
                raise OSError("fstat failed")

            if not S_ISREG(st.st_mode):
                raise OSError("not a regular file")

            file_size = st.st_size
            if file_size < 8:
                raise ValueError("file too small")

            last4 = <unsigned char*> malloc(4)
            if not last4:
                raise MemoryError()
            meta_buf = <unsigned char*> malloc(32)
            if not meta_buf:
                raise MemoryError()

            self.meta_end = <unsigned long>(file_size - 4)

            # meta start
            r = pread(fd, last4, 4, <off_t>(file_size - 4))
            if r != 4:
                raise RuntimeError("failed to read trailing meta offset")
            self.meta_start = _be32_from_buf(last4)
            if self.meta_start > self.meta_end:
                raise ValueError("invalid meta_start")

            numHashChunks = (self.meta_start + CHUNK_SIZE - 1) // CHUNK_SIZE
            meta_header_offset = self.meta_start + 4 + numHashChunks * 2

            # meta data
            if meta_header_offset + 32 > file_size:
                raise ValueError("metadata header outside file")
            r = pread(fd, meta_buf, 32, <off_t>meta_header_offset)
            if r >= 32:
                self.fetch_count = _be32_from_buf(meta_buf + 4)
                self.last_fetch = _be32_from_buf(meta_buf + 8)
                self.last_modified = _be32_from_buf(meta_buf + 12)
                self.frequency = _be32_from_buf(meta_buf + 16)
                self.expiration = _be32_from_buf(meta_buf + 20)
                key_size = _be32_from_buf(meta_buf + 24)

            # key
            if key_size > 0 and key_size < MAX_KEY_SIZE:
                keylen = key_size
                if keylen > MAX_ALLOC:
                    raise MemoryError()
                keybuf = <char*> malloc(keylen)
                if not keybuf:
                    raise MemoryError()
                if meta_header_offset + 32 + keylen > file_size:
                    raise ValueError("key outside file")
                r = pread(fd, keybuf, keylen, <off_t>(meta_header_offset + 32))
                if r > 0:
                    actual = r
                    for i in range(actual):
                        if keybuf[i] == 0:
                            actual = i
                            break
                    pykey = PyUnicode_DecodeUTF8(keybuf, actual, "replace")
                    if pykey is not None:
                        key_str = <str>pykey
                        idx = key_str.find(':')
                        if idx != -1:
                            self.key = key_str[idx+1:]
                        else:
                            self.key = key_str
                free(keybuf)
                keybuf = NULL
            self.map_start = self.meta_start + key_size + 1
        finally:
            if last4 is not NULL:
                free(last4)
            if meta_buf is not NULL:
                free(meta_buf)
            if keybuf is not NULL:
                free(keybuf)
            if fd >= 0:
                close(fd)

    cpdef dict load_map(self):
        if self._map_cache is not None:
            return self._map_cache

        cdef dict result = {}
        cdef int fd = -1
        cdef unsigned long length
        cdef unsigned char *buf = NULL
        cdef ssize_t r
        cdef unsigned char *ptr
        cdef unsigned char *key_start
        cdef unsigned char *end
        cdef unsigned char *next_null
        cdef Py_ssize_t klen, vlen
        cdef object kstr = None
        cdef object vstr = None

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

            fd = c_open(self.file_path.encode('utf-8'), O_RDONLY | O_NOFOLLOW | O_CLOEXEC)
            if fd < 0:
                raise OSError("open failed")
            buf = <unsigned char*> malloc(length)
            if not buf:
                raise MemoryError()
            r = pread(fd, buf, length, <off_t>self.map_start)
            close(fd)
            fd = -1
            if r <= 0:
                free(buf)
                self._add_metadata_to_result(result)
                self._map_cache = result
                return result

            ptr = buf
            end = buf + r

            while ptr < end:
                key_start = ptr
                next_null = <unsigned char*> memchr(ptr, 0, end - ptr)
                if not next_null:
                    break
                klen = <Py_ssize_t>(next_null - ptr)
                ptr = next_null + 1
                if ptr >= end:
                    break
                next_null = <unsigned char*> memchr(ptr, 0, end - ptr)
                if not next_null:
                    break
                vlen = <Py_ssize_t>(next_null - ptr)
                if klen > 0 and vlen > 0:
                    try:
                        kstr = PyUnicode_DecodeUTF8(<char*>key_start, klen, "ignore")
                    except Exception:
                        kstr = None
                    try:
                        vstr = PyUnicode_DecodeUTF8(<char*>ptr, vlen, "ignore")
                    except Exception:
                        vstr = None
                    if kstr is not None and vstr is not None:
                        try:
                            result[<str>kstr] = <str>vstr
                        except Exception:
                            pass
                ptr = next_null + 1

            free(buf)
            buf = NULL
            self._add_metadata_to_result(result)
            self._map_cache = result
            return result
        except Exception:
            if buf is not NULL:
                free(buf)
            if fd >= 0:
                try:
                    close(fd)
                except:
                    pass
            self._add_metadata_to_result(result)
            self._map_cache = result
            return result
    
    cdef void _add_metadata_to_result(self, dict result):
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

    cpdef bytes get_data(self):
        if self.meta_start == 0:
            return b''

        if self.meta_start > MAX_ALLOC:
            raise MemoryError("refusing huge allocation")
        cdef int fd = -1
        cdef unsigned char *buf = NULL
        cdef ssize_t r
        cdef bytes result
        cdef bytes pathb = self.file_path.encode('utf-8')

        try:
            fd = c_open(pathb, O_RDONLY | O_NOFOLLOW | O_CLOEXEC)
            if fd < 0:
                raise OSError("open failed")
            buf = <unsigned char*> malloc(self.meta_start)
            if not buf:
                raise MemoryError()
            r = pread(fd, buf, self.meta_start, 0)
            if r <= 0:
                return b''
            result = PyBytes_FromStringAndSize(<char*>buf, r)
            if not result:
                raise MemoryError()
            return result
        finally:
            if buf is not NULL:
                free(buf)
            if fd >= 0:
                close(fd)

    cpdef bint save(self, str path):
        cdef bytes data = self.get_data()
        if not data:
            return False
        try:
            with open(path, 'wb') as f:
                f.write(data)
            return True
        except Exception as e:
            raise RuntimeError(f"Failed to save: {e}")

    cpdef HttpHeader get_header(self):
        try:
            meta_map = self.load_map()
            header_str = meta_map.get('response-head', '')
            return HttpHeader(header_str)
        except Exception:
            return HttpHeader("HTTP/1.1 200 OK\r\n")


# FirefoxCacheIndex
cdef class FirefoxCacheIndex:
    
    cdef public dict header
    cdef public list records
    
    def __init__(self, path=None):
        self.header = {}
        self.records = []
        if path:
            self._read_index(str(path))

    cdef void _read_index(self, str path):
        cdef int fd = -1
        cdef stat st
        cdef unsigned char *header_buf = NULL
        cdef unsigned char *record_buf = NULL
        cdef ssize_t r
        cdef unsigned long offset
        cdef int frequency, expires, app_id
        cdef unsigned int flags, size
        cdef bytes pathb = path.encode('utf-8')
        try:
            fd = c_open(pathb, O_RDONLY | O_NOFOLLOW | O_CLOEXEC)

            if fd < 0:
                return
            if fstat(fd, &st) != 0:
                return
            if not S_ISREG(st.st_mode):
                return

            header_buf = <unsigned char*> malloc(12)
            if not header_buf:
                return
            record_buf = <unsigned char*> malloc(36)
            if not record_buf:
                return

            r = pread(fd, header_buf, 12, 0)
            if r == 12:
                self.header['mVersion'] = _be32_from_buf(header_buf)
                self.header['mTimeStamp'] = _be32_from_buf(header_buf + 4)
                self.header['mIsDirty'] = _be32_from_buf(header_buf + 8)
            offset = 12
            while True:
                r = pread(fd, record_buf, 36, offset)
                if r != 36:
                    break
                hexb = PyBytes_FromStringAndSize(<char*>record_buf, HASH_SIZE)
                if hexb:
                    frequency = <int>_be32_from_buf(record_buf + 20)
                    expires = <int>_be32_from_buf(record_buf + 24)
                    app_id = <int>_be32_from_buf(record_buf + 28)
                    flags = <unsigned int>record_buf[32]
                    size = (<unsigned int>((record_buf[33] << 16) | (record_buf[34] << 8) | record_buf[35]))
                    self.records.append({
                        'hash': (<bytes>hexb).hex().upper(),
                        'frequency': frequency,
                        'expires': expires,
                        'appId': app_id,
                        'flags': flags,
                        'size': size
                    })
                offset += 36
        except Exception as e:
            raise RuntimeError(f"Error reading index: {e}")
        finally:
            if header_buf is not NULL:
                free(header_buf)
            if record_buf is not NULL:
                free(record_buf)
            if fd >= 0:
                close(fd)


# FirefoxCache
cdef class FirefoxCache:
    cdef public list records
    cdef public object index

    def __init__(self, str cache2_dir):
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

    def find(self, str key):
        for entry in self.records:
            if entry.key == key:
                return entry
        raise KeyError(f"Key not found: {key}")

    def find_save(self, str key, str path):
        entry = self.find(key)
        entry.save(path)

    def keys(self):
        return [entry.key for entry in self.records]
