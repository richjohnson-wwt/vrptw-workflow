# Geocoding Cache Refactoring

## Overview

This document describes the refactoring of geocoding cache logic from `app/tabs/geocode_tab.py` into a dedicated `GeocodingCache` class in `app/geocoding/cache.py`.

## Motivation

The cache logic was previously duplicated in both `GeocodeWorker` and `GeocodeTab` classes, leading to:
- **Code duplication**: ~140 lines of identical cache methods in two places
- **Maintenance burden**: Changes to cache logic required updates in multiple locations
- **Poor separation of concerns**: Cache logic mixed with worker and UI logic
- **Difficult testing**: Cache operations couldn't be tested independently

## Changes Made

### 1. Created `app/geocoding/cache.py`

A new `GeocodingCache` class that encapsulates all cache operations:

```python
class GeocodingCache:
    """Manages SQLite-based caching for geocoding results."""
    
    def __init__(self, cache_dir: Optional[Path] = None)
    def get_cache_path(self) -> Path
    def connect(self) -> sqlite3.Connection
    def get(self, normalized_address: str) -> Optional[Dict[str, Any]]
    def put(self, normalized_address: str, lat: Optional[float], 
            lon: Optional[float], display_name: str, source: str)
    def clear(self) -> bool
    
    @staticmethod
    def normalize_address(address: str, city: str, state: str, zip5: str) -> str
```

**Key Features:**
- Thread-safe: Each operation opens its own connection
- Configurable cache directory (defaults to `~/Documents/VRPTW/.cache/`)
- Context manager support for convenient usage
- Comprehensive docstrings and type hints

### 2. Updated `GeocodeWorker` Class

**Removed methods** (67 lines):
- `_cache_path()`
- `_ensure_cache()`
- `_normalize_address()`
- `_cache_get()`
- `_cache_put()`

**Added:**
- `self.cache = GeocodingCache()` in `__init__()`

**Updated usage in `run()` method:**
```python
# Before:
conn = self._ensure_cache()
self.log.emit(f"Using cache: {self._cache_path()}")
norm = self._normalize_address(address, city, st, zip5)
cached = self._cache_get(conn, norm)
self._cache_put(conn, norm, lat, lon, disp, source=provider_name)

# After:
self.log.emit(f"Using cache: {self.cache.get_cache_path()}")
norm = GeocodingCache.normalize_address(address, city, st, zip5)
cached = self.cache.get(norm)
self.cache.put(norm, lat, lon, disp, source=provider_name)
```

### 3. Updated `GeocodeTab` Class

**Removed methods** (73 lines):
- `_cache_path()`
- `_ensure_cache()`
- `_normalize_address()`
- `_cache_get()`
- `_cache_put()`

**Added:**
- `self.cache = GeocodingCache()` in `__init__()`

**Updated `on_clear_cache()` method:**
```python
# Before:
p = self._cache_path()
if p.exists():
    p.unlink()
    self.log_append(f"Cache cleared: {p}")

# After:
cache_path = self.cache.get_cache_path()
if self.cache.clear():
    self.log_append(f"Cache cleared: {cache_path}")
```

### 4. Updated `app/geocoding/__init__.py`

Added `GeocodingCache` to module exports:
```python
from .cache import GeocodingCache

__all__ = ["GeocodingStrategy", "NominatimStrategy", "GoogleMapsStrategy", "GeocodingCache"]
```

### 5. Removed Unused Import

Removed `import sqlite3` from `geocode_tab.py` since SQLite operations are now handled by `GeocodingCache`.

### 6. Created Comprehensive Unit Tests

Created `tests/test_geocoding_cache.py` with 15 test cases covering:
- Initialization with default and custom directories
- Database schema creation
- Storing and retrieving successful geocodes
- Storing and retrieving failed geocodes
- Updating existing entries
- Address normalization
- Cache clearing
- Context manager usage
- Multiple operations
- Thread-safety simulation

## Benefits

### Code Quality
- **Eliminated 140+ lines of duplicated code**
- **Single Responsibility Principle**: Cache logic is now isolated
- **Better encapsulation**: Cache implementation details hidden from workers and UI

### Maintainability
- **Single source of truth**: Cache changes only need to happen in one place
- **Easier to extend**: Can add features like cache expiration, statistics, or migration
- **Clear API**: Well-documented methods with type hints

### Testability
- **Independent testing**: Cache operations can be tested without UI or worker logic
- **Comprehensive test coverage**: 15 test cases covering all functionality
- **Easy to mock**: Simple interface for testing components that use the cache

### Consistency
- **Guaranteed consistency**: Both worker and UI use the same cache implementation
- **No drift**: Eliminates risk of methods diverging between classes

## Cache Schema

The cache uses SQLite with the following schema:

```sql
CREATE TABLE addresses (
  id INTEGER PRIMARY KEY,
  normalized_address TEXT UNIQUE,
  latitude REAL,
  longitude REAL,
  display_name TEXT,
  source TEXT,
  updated_at TEXT
)

CREATE UNIQUE INDEX idx_addresses_norm ON addresses(normalized_address)
```

## Usage Examples

### Basic Usage
```python
from app.geocoding import GeocodingCache

cache = GeocodingCache()

# Store a successful geocode
cache.put("123 Main St, Springfield, IL 62701, USA", 
          39.7817, -89.6501, "Springfield, IL", source="nominatim")

# Retrieve from cache
result = cache.get("123 Main St, Springfield, IL 62701, USA")
if result:
    print(f"Lat: {result['lat']}, Lon: {result['lon']}")

# Store a failed geocode
cache.put("Invalid Address", None, None, "", source="none")

# Clear the cache
cache.clear()
```

### With Context Manager
```python
with GeocodingCache() as cache:
    result = cache.get(normalized_address)
    if not result:
        # geocode and store
        cache.put(normalized_address, lat, lon, display_name, source)
```

### Custom Cache Directory
```python
from pathlib import Path

cache = GeocodingCache(cache_dir=Path("/custom/cache/dir"))
```

## Backward Compatibility

✅ **Fully backward compatible**
- Cache file location unchanged: `~/Documents/VRPTW/.cache/nominatim.sqlite`
- Cache schema unchanged
- All existing cached data remains accessible
- No migration required

## Testing

### Unit Tests
Run the cache unit tests:
```bash
python3 -m pytest tests/test_geocoding_cache.py -v
```

### Integration Testing
The refactored code maintains the same behavior as before:
1. Start the application
2. Select a workspace with addresses
3. Run geocoding on a state
4. Verify cached results are used on subsequent runs
5. Clear cache and verify it's deleted
6. Re-run geocoding to verify cache is rebuilt

## Files Modified

- ✅ `app/geocoding/cache.py` - **Created** (200 lines)
- ✅ `app/geocoding/__init__.py` - **Modified** (added export)
- ✅ `app/tabs/geocode_tab.py` - **Modified** (removed 140+ lines, updated usage)
- ✅ `tests/test_geocoding_cache.py` - **Created** (220 lines)

## Lines of Code Impact

- **Added**: 420 lines (200 implementation + 220 tests)
- **Removed**: 141 lines (duplicated cache methods)
- **Net change**: +279 lines
- **Code duplication eliminated**: 140 lines

## Future Enhancements

The new `GeocodingCache` class makes it easy to add:
- **Cache expiration**: Automatically refresh old entries
- **Cache statistics**: Track hit rates, size, etc.
- **Cache migration**: Version the schema and migrate data
- **Multiple cache backends**: Support Redis, Memcached, etc.
- **Cache warming**: Pre-populate cache with known addresses
- **Cache compression**: Reduce disk usage for large caches

## Related Documentation

- `NOMINATIM_IMPROVEMENTS.md` - Nominatim strategy enhancements
- `GEOCODING_ERROR_LOGGING.md` - Error logging feature
- Strategy pattern refactoring (see memory)

## Conclusion

This refactoring successfully extracts cache logic into a dedicated, well-tested module that follows SOLID principles and improves code maintainability. The changes are backward compatible and require no data migration.
