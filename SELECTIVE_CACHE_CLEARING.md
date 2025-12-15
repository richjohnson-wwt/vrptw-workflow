# Selective Cache Clearing Feature

## Overview

This document describes the selective cache clearing feature that allows users to clear specific cache entries by state or individual site, rather than clearing the entire cache.

## Motivation

The original "Clear Cache" button deleted the entire cache database file, which was:
- **Too aggressive**: Cleared all cached geocoding results for all states
- **Inefficient**: Required re-geocoding all addresses, even those that were correct
- **Inflexible**: No way to clear only problematic addresses

The selective clearing feature provides granular control over which cache entries to remove.

## Features

### 1. Clear Cache by State (Context Menu)

**How to use:**
1. Navigate to the "Geocode View" tab
2. Right-click on a state in the States list
3. Select "Clear Cache for [STATE] (X entries)"
4. Confirm the action

**What it does:**
- Removes all cached geocoding results for addresses in that state
- Shows statistics: total entries, successful vs. failed
- Preserves cache entries for other states
- Next geocoding run will re-geocode only the cleared addresses

**Use cases:**
- A state's addresses were geocoded with incorrect settings
- You want to re-geocode a specific state with a different provider
- Testing geocoding improvements on a single state

### 2. Clear Cache by Site (Context Menu)

**How to use:**
1. Navigate to the "Geocode View" tab
2. Select a state to view its geocoded sites
3. Right-click on a specific site in the table
4. Select "Clear Cache for Site [ID]"
5. Confirm the action

**What it does:**
- Removes the cache entry for that specific address
- Next geocoding run will re-geocode only that address
- All other addresses remain cached

**Use cases:**
- A specific address was geocoded incorrectly
- You've corrected an address and want to re-geocode it
- Testing geocoding on individual problematic addresses

### 3. Clear All Cache (Button)

**How to use:**
1. Click the "Clear Cache" button (existing functionality)
2. Confirm the action

**What it does:**
- Deletes the entire cache database file
- All addresses will be re-geocoded on next run

**Use cases:**
- Starting fresh with a new geocoding provider
- Cache corruption or database issues
- Major changes to address normalization logic

## Implementation Details

### New `GeocodingCache` Methods

#### `clear_by_address(normalized_address: str) -> bool`
Clears a single cache entry by its normalized address.

**Returns:** `True` if entry was deleted, `False` if not found.

```python
cache = GeocodingCache()
deleted = cache.clear_by_address("123 Main St, Springfield, IL 62701, USA")
```

#### `clear_by_addresses(normalized_addresses: list[str]) -> int`
Clears multiple cache entries at once.

**Returns:** Number of entries deleted.

```python
cache = GeocodingCache()
addresses = ["Addr1", "Addr2", "Addr3"]
deleted = cache.clear_by_addresses(addresses)
print(f"Deleted {deleted} entries")
```

#### `clear_by_state(state_code: str) -> int`
Clears all cache entries for a specific state.

**Returns:** Number of entries deleted.

```python
cache = GeocodingCache()
deleted = cache.clear_by_state("IL")
print(f"Deleted {deleted} entries for Illinois")
```

#### `get_cache_stats(state_code: Optional[str] = None) -> Dict[str, int]`
Gets statistics about cached entries.

**Returns:** Dictionary with keys: `total`, `successful`, `failed`.

```python
cache = GeocodingCache()

# All states
stats = cache.get_cache_stats()
print(f"Total: {stats['total']}, Successful: {stats['successful']}, Failed: {stats['failed']}")

# Specific state
stats = cache.get_cache_stats(state_code="IL")
print(f"Illinois - Total: {stats['total']}, Successful: {stats['successful']}")
```

### UI Components

#### State List Context Menu
- Triggered by right-clicking on a state in the States list
- Shows cache statistics for the state
- Provides "Clear Cache for [STATE]" action
- Displays informational stats (successful/failed counts)

#### Table Context Menu
- Triggered by right-clicking on a site in the geocoded table
- Provides "Clear Cache for Site [ID]" action
- Shows the address that will be cleared

### Confirmation Dialogs

All cache clearing actions require confirmation:

**State clearing:**
```
Clear State Cache?

Clear 45 cache entries for state IL?

(32 successful, 13 failed)

These addresses will be re-geocoded on the next run.

[No] [Yes]
```

**Site clearing:**
```
Clear Site Cache?

Clear cache for site 123?

Address: 123 Main St, Springfield, IL 62701, USA

This address will be re-geocoded on the next run.

[No] [Yes]
```

## Technical Details

### State Matching Pattern

The `clear_by_state()` method uses SQL LIKE pattern matching:

```sql
DELETE FROM addresses WHERE normalized_address LIKE '%, IL %'
```

This matches addresses in the normalized format:
- `"123 Main St, Springfield, IL 62701, USA"`
- `"456 Oak Ave, Chicago, IL 60601, USA"`

The pattern is case-insensitive (state codes are uppercased).

### Cache Statistics Query

Statistics are calculated using SQL aggregation:

```sql
-- Total entries
SELECT COUNT(*) FROM addresses WHERE normalized_address LIKE '%, IL %'

-- Successful entries (have coordinates)
SELECT COUNT(*) FROM addresses 
WHERE normalized_address LIKE '%, IL %' 
AND latitude IS NOT NULL 
AND longitude IS NOT NULL
```

Failed entries = Total - Successful

### Thread Safety

All cache operations are thread-safe:
- Each operation opens its own database connection
- Connections are closed in `finally` blocks
- No shared connection state between operations

## Testing

### Unit Tests

Added 10 new test cases in `tests/test_geocoding_cache.py`:

1. `test_clear_by_address` - Clear single address
2. `test_clear_by_address_nonexistent` - Clear non-existent address
3. `test_clear_by_addresses` - Clear multiple addresses
4. `test_clear_by_addresses_empty_list` - Clear empty list
5. `test_clear_by_state` - Clear by state code
6. `test_clear_by_state_case_insensitive` - Case insensitivity
7. `test_get_cache_stats_all` - Stats for all entries
8. `test_get_cache_stats_by_state` - Stats for specific state
9. `test_get_cache_stats_empty` - Stats for empty cache

Run tests:
```bash
python3 -m pytest tests/test_geocoding_cache.py -v
```

### Manual Testing Checklist

- [ ] Right-click on state in States list shows context menu
- [ ] Context menu shows correct entry count for state
- [ ] Context menu shows correct successful/failed stats
- [ ] Clearing state cache removes only that state's entries
- [ ] Confirmation dialog shows correct information
- [ ] Log tab shows success message with count
- [ ] Geocode status updates after clearing
- [ ] Right-click on site in table shows context menu
- [ ] Clearing site cache removes only that entry
- [ ] Re-geocoding after clearing only processes cleared addresses
- [ ] "Clear Cache" button still works for clearing all
- [ ] Context menu doesn't appear on empty areas

## Benefits

### User Experience
✅ **More control** - Clear only what needs to be re-geocoded  
✅ **Safer** - Less likely to accidentally clear entire cache  
✅ **Informative** - See statistics before clearing  
✅ **Efficient** - Re-geocode only problematic addresses  
✅ **Discoverable** - Context menus are intuitive  

### Performance
✅ **Faster re-geocoding** - Only clear what's needed  
✅ **Preserves good data** - Keep successful geocodes  
✅ **Selective testing** - Test improvements on specific states  

### Workflow
✅ **Iterative improvement** - Fix addresses one at a time  
✅ **State-by-state processing** - Clear and re-geocode by state  
✅ **Error correction** - Easy to fix individual mistakes  

## Backward Compatibility

✅ **Fully backward compatible**
- Existing "Clear Cache" button functionality preserved
- Cache database schema unchanged
- No migration required
- All existing cache entries remain valid

## Future Enhancements

Possible future improvements:

1. **Bulk site clearing**: Select multiple sites and clear all at once
2. **Clear failed only**: Context menu option to clear only failed geocodes
3. **Clear by source**: Clear entries from specific provider (e.g., "nominatim")
4. **Cache expiration**: Automatically clear entries older than X days
5. **Export cache stats**: Export statistics to CSV for analysis
6. **Visual indicators**: Show cache status icons in state list
7. **Undo clearing**: Temporarily store cleared entries for undo

## Related Documentation

- `CACHE_REFACTORING.md` - Initial cache extraction refactoring
- `NOMINATIM_IMPROVEMENTS.md` - Nominatim strategy enhancements
- `GEOCODING_ERROR_LOGGING.md` - Error logging feature

## Summary

The selective cache clearing feature provides granular control over geocoding cache management through intuitive context menus. Users can now clear cache entries by state or individual site, making it easier to fix geocoding errors and test improvements without losing all cached data.
