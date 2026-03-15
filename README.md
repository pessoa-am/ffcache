# ffcache

Firefox cache python extractor - extract and export Firefox cache entries

## About This Project

This is a Python port of the original [ffcache](https://github.com/shosatojp/ffcache) project by [shosatojp](https://github.com/shosatojp), which was originally written in C++ with pybind11. This port provides two implementations:

- **Cython implementation** (`ffcache/ffcache.pyx`)
- **Pure Python implementation** (`ffcache.py`) - Pure Python reference script using `struct`

Both implementations aim 100% API compatibility with the original C++ version. The pure Python version serves as a reference implementation and is not distributed via PyPI.

## Usage

### Get list of cache

```sh
FFCACHE_DIR=~/.cache/mozilla/firefox/hoge.default/cache2 ffcache --list
```

### Save cached file

```sh
ffcache --key "https://example.com" --cache /path/to/cache2 --out index.html
```

### Options

```sh
[usage]
ffcache [OPTIONS]
--list  -l      list all keys
--cache -c      cache2 directory
--key   -k      key
--out   -o      output path
```

### Example

```py
from ffcache import FirefoxCache, FirefoxCacheEntry
from ffcache.helper import save
import urllib.parse
import os
import brotli
import gzip
import zlib
import sys

cache_dir = os.environ['FFCACHE_DIR']
out_dir = 'tmp'

if not os.path.exists(out_dir):
    os.mkdir(out_dir)

cache = FirefoxCache(cache_dir)

entry: FirefoxCacheEntry

for entry in cache.records:
    url = entry.key
    print(url)

    filename = urllib.parse.quote(url, safe='')[:255]
    out_path = os.path.join(out_dir, filename)

    try:
        save(entry, out_path)
    except:
        pass
```

There's also a more comprehensive `example.py` in the repository.

## Installation

```sh
pip install ffcache
```

## Build

### Build on host

```sh
sudo apt-get install -y python3-dev python3-pip
pip install cython brotli
python setup.py build_ext --inplace
```

Or install in development mode:

```sh
pip install -e .
```

## License

MIT

## Attribution

This is a python port of the original [ffcache](https://github.com/shosatojp/ffcache) project by [Sho Sato](https://github.com/shosatojp).

The `example.py` script functionality is modeled after the [python2 scripts by James Habben](https://github.com/JamesHabben/FirefoxCache2).
