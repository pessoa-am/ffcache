import os
import sys
import argparse
import urllib.parse
import csv
from datetime import datetime
from ffcache import FirefoxCache
from ffcache.helper import save

# ============================================================================
# Helper Functions
# ============================================================================

def url_to_filepath(url: str, base_dir: str) -> tuple:
    """Convert a URL to a filepath structure."""
    parsed_url = urllib.parse.urlparse(url)
    domain = urllib.parse.quote(parsed_url.netloc or 'unknown', safe='')
    path = parsed_url.path or '/index.html'
    is_directory = path.endswith('/')
    path_parts = [urllib.parse.quote(p, safe='') for p in path.split('/') if p]
    
    if is_directory:
        file_dir = os.path.join(base_dir, domain, *path_parts)
        base_filename = 'index.html'
    else:
        if not path_parts:
            path_parts = ['index.html']
        file_dir = os.path.join(base_dir, domain, *path_parts[:-1])
        base_filename = path_parts[-1][:255]
    
    return file_dir, base_filename

def format_timestamp(timestamp):
    """Convert Unix timestamp to readable format."""
    if not timestamp or timestamp == 0:
        return ''
    try:
        return datetime.fromtimestamp(timestamp / 1000.0).strftime('%Y-%m-%d %H:%M:%S')
    except (ValueError, OSError):
        return str(timestamp)

def format_hex(value):
    """Convert value to hex format."""
    if not value or value == 0:
        return '0x0'
    try:
        return hex(int(value))
    except (ValueError, TypeError):
        return str(value)

# ============================================================================
# CSV Export Functions
# ============================================================================

def write_index_csv(cache: FirefoxCache, output_path: str) -> int:
    """Write cache index metadata to CSV."""
    try:
        with open(output_path, 'w', newline='') as csvfile:
            writer = csv.writer(csvfile, quoting=csv.QUOTE_NONNUMERIC)
            index_headers = ['hash', 'frequency', 'expires', 'appId', 'flags', 'size']
            writer.writerow(index_headers)
            
            if cache.index:
                for record in cache.index.records:
                    csv_data = [
                        record.get('hash', ''),
                        format_hex(record.get('frequency', 0)),
                        format_timestamp(record.get('expires', 0)),
                        format_hex(record.get('appId', 0)),
                        format_hex(record.get('flags', 0)),
                        record.get('size', 0)
                    ]
                    writer.writerow(csv_data)
            else:
                print("Warning: Cache index not available, writing empty index CSV", file=sys.stderr)
                return 1
        
        print("Index CSV written to: {0}".format(output_path))
        return 0
    except Exception as e:
        print("Error writing index CSV: {0}".format(e), file=sys.stderr)
        return 1


def write_file_csv(cache: FirefoxCache, output_path: str) -> int:
    """Write cache entry details to CSV."""
    try:
        with open(output_path, 'w', newline='') as csvfile:
            writer = csv.writer(csvfile, quoting=csv.QUOTE_NONNUMERIC)

            file_headers = ['Fetch Count', 'Last Fetch', 'Last Modified', 'Frequency', 'Expiration', 'Flags', 'URL', 'Hash']
            writer.writerow(file_headers)
            
            for i, entry in enumerate(cache.records):
                try:
                    url = entry.key
                    hash = os.path.basename(entry.file_path)
                    csv_data = [
                        entry.fetch_count or 0,
                        format_timestamp(entry.last_fetch or 0),
                        format_timestamp(entry.last_modified or 0),
                        format_hex(entry.frequency or 0),
                        format_timestamp(entry.expiration or 0),
                        format_hex(entry.flags or 0),
                        url,
                        hash
                    ]
                    writer.writerow(csv_data)
                except Exception as e:
                    print("    Error writing file entry {0}: {1}".format(i, e), file=sys.stderr)
        
        print("File CSV written to: {0}".format(output_path))
        return 0
    except Exception as e:
        print("Error writing file CSV: {0}".format(e), file=sys.stderr)
        return 1


# ============================================================================
# Data Export Functions
# ============================================================================

def save_data(cache_dir: str, output_dir: str, structured: bool = False) -> int:
    """Save cached files to disk."""
    try:
        cache = FirefoxCache(cache_dir)
        
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)
        
        successfully_saved = 0
        errors = 0
        
        for i, entry in enumerate(cache.records):
            try:
                url = entry.key
                print("Processing [{0}/{1}]: {2}".format(i+1, len(cache.records), url))
                
                if structured:
                    file_dir, base_filename = url_to_filepath(url, output_dir)
                    os.makedirs(file_dir, exist_ok=True)
                    out_path = os.path.join(file_dir, base_filename)
                    should_save = True
                    
                    if os.path.exists(out_path):
                        existing_size = os.path.getsize(out_path)
                        data_size = len(entry.get_data())
                        if existing_size == data_size:
                            should_save = False
                        else:
                            fname, ext = os.path.splitext(base_filename)
                            counter = 1
                            found_new_path = False
                            while not found_new_path:
                                new_filename = "{0}_{1}{2}".format(fname, counter, ext) if ext else "{0}_{1}".format(fname, counter)
                                out_path = os.path.join(file_dir, new_filename)
                                if not os.path.exists(out_path):
                                    found_new_path = True
                                else:
                                    existing_size = os.path.getsize(out_path)
                                    if existing_size == data_size:
                                        should_save = False
                                        found_new_path = True
                                counter += 1
                else:
                    filename = urllib.parse.quote(url, safe='')[:255]
                    os.makedirs(output_dir, exist_ok=True)
                    out_path = os.path.join(output_dir, filename)
                    should_save = True
                
                if should_save:
                    save(entry, out_path)
                    successfully_saved += 1
                
            except Exception as e:
                errors += 1
                print("  Error on entry {0}: {1}".format(i, e), file=sys.stderr)
        
        print("\nSave Data Complete:")
        print("  Successfully saved: {0}".format(successfully_saved))
        print("  Errors: {0}".format(errors))
        print("  Output directory: {0}".format(output_dir))
        
        return 0 if errors == 0 else 1
    except Exception as e:
        print("Error during save_data: {0}".format(e), file=sys.stderr)
        return 1


# ============================================================================
# Main CLI
# ============================================================================

def main():
    """Main CLI interface."""
    try:
        parser = argparse.ArgumentParser(
            description='Firefox cache extraction and export utilities',
            formatter_class=argparse.RawDescriptionHelpFormatter
        )
        
        subparsers = parser.add_subparsers(dest='command', help='Available commands')
        
        save_parser = subparsers.add_parser('save_data', help='Save cached files to disk')
        save_parser.add_argument('-c', '--cache', dest='cache_dir', default=None, help='Path to Firefox cache directory (overrides FFCACHE_DIR env var)')
        save_parser.add_argument('-o', '--out', dest='output', default='output', help='Output directory (default: output)')
        save_parser.add_argument('-s', '--structured', action='store_true', 
                                help='Save in structured directory tree based on URL')
        
        index_parser = subparsers.add_parser('index_csv', help='Export index metadata to CSV')
        index_parser.add_argument('-c', '--cache', dest='cache_dir', default=None, help='Path to Firefox cache directory (overrides FFCACHE_DIR env var)')
        index_parser.add_argument('-o', '--out', dest='output', default='index.csv', help='Output CSV file (default: index.csv)')
        
        file_parser = subparsers.add_parser('file_csv', help='Export file details to CSV')
        file_parser.add_argument('-c', '--cache', dest='cache_dir', default=None, help='Path to Firefox cache directory (overrides FFCACHE_DIR env var)')
        file_parser.add_argument('-o', '--out', dest='output', default='file.csv', help='Output CSV file (default: file.csv)')
        
        args = parser.parse_args()
        cache_dir = args.cache_dir or os.getenv('FFCACHE_DIR')
        
        if not cache_dir:
            print("Error: Cache directory not specified. Use -c/--cache or set FFCACHE_DIR environment variable", file=sys.stderr)
            return 1
        
        if not args.command:
            parser.print_help()
            return 1
        elif args.command == 'save_data':
            return save_data(cache_dir, args.output, structured=args.structured)
        elif args.command == 'index_csv':
            try:
                cache = FirefoxCache(cache_dir)
                return write_index_csv(cache, args.output)
            except Exception as e:
                print("Error loading cache: {0}".format(e), file=sys.stderr)
                return 1
        elif args.command == 'file_csv':
            try:
                cache = FirefoxCache(cache_dir)
                return write_file_csv(cache, args.output)
            except Exception as e:
                print("Error loading cache: {0}".format(e), file=sys.stderr)
                return 1
        
        return 0
    except Exception as e:
        print("Error in main: {0}".format(e), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
