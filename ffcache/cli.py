import argparse
import sys
import os

from . import __version__
from _ffcache import FirefoxCache


def list_keys(ffcache_dir: str) -> int:
    try:
        cache = FirefoxCache(ffcache_dir)
        print(f"Found {len(cache.records)} cache entries:\n")
        for i, entry in enumerate(cache.records, 1):
            print(f"{i:5d}. {entry.key}")
        return 0
    except Exception as e:
        print(f"Error reading cache: {e}", file=sys.stderr)
        return 1


def export_key(ffcache_dir: str, key: str, output_path: str) -> int:
    try:
        cache = FirefoxCache(ffcache_dir)
        
        entry = None
        for record in cache.records:
            if record.key == key:
                entry = record
                break
        
        if entry is None:
            print(f"Error: Key not found: {key}", file=sys.stderr)
            print(f"Use --list to see available keys", file=sys.stderr)
            return 1
        
        output_dir = os.path.dirname(output_path)
        if output_dir and not os.path.exists(output_dir):
            os.makedirs(output_dir, exist_ok=True)
        
        if hasattr(entry, 'save'):
            entry.save(output_path)
        
        print(f"Cache entry exported to: {output_path}")
        return 0
    except Exception as e:
        print(f"Error exporting cache entry: {e}", file=sys.stderr)
        return 1


def main() -> int:
    parser = argparse.ArgumentParser(
        prog='ffcache',
        description='Firefox cache python extractor - extract and export Firefox cache entries',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  FFCACHE_DIR=~/.cache/mozilla/firefox/hoge.default/cache2 ffcache --list
  ffcache --key "https://example.com" --cache /path/to/cache2 --out index.html
        """
    )
    
    parser.add_argument(
        '-c', '--cache',
        dest='ffcache_dir',
        default=None,
        help='Path to Firefox cache2 directory (overrides FFCACHE_DIR env var)'
    )
    
    parser.add_argument(
        '-l', '--list',
        action='store_true',
        help='List all cache keys'
    )
    
    parser.add_argument(
        '-k', '--key',
        dest='key',
        help='Specific cache key/URL to export'
    )
    
    parser.add_argument(
        '-o', '--out',
        dest='output',
        help='Output file path (required when using --key)'
    )
    
    parser.add_argument(
        '--version',
        action='version',
        version='%(prog)s {}'.format(__version__)
    )
    
    args = parser.parse_args()
    
    ffcache_dir = args.ffcache_dir or os.getenv('FFCACHE_DIR')
    
    if not ffcache_dir:
        print("Error: Cache directory not specified. Use -c/--cache or set FFCACHE_DIR environment variable", file=sys.stderr)
        return 1
    
    if not os.path.isdir(ffcache_dir):
        print(f"Error: Cache directory not found: {ffcache_dir}", file=sys.stderr)
        return 1
    
    if args.list:
        return list_keys(ffcache_dir)
    
    if args.key:
        if not args.output:
            print("Error: --out is required when using --key", file=sys.stderr)
            return 1
        return export_key(ffcache_dir, args.key, args.output)
    
    parser.print_help()
    return 1


if __name__ == '__main__':
    sys.exit(main())
