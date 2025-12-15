# Geocoding Error Logging Feature

## Overview
Failed geocoding attempts are now tracked separately and written to `geocode-errors.csv` files per state. This provides visibility into addresses that couldn't be geocoded and helps identify data quality issues.

## Implementation Details

### Error CSV Structure
Location: `<workspace>/<state>/geocode-errors.csv`

**Columns:**
- `id`: Site ID from original addresses.csv
- `address`: Original address field
- `city`: Original city field
- `state`: Original state field
- `zip`: Original zip code field
- `normalized_address`: The normalized query string used for geocoding
- `strategy`: Geocoding provider used (e.g., "nominatim", "google_maps")
- `reason`: Why geocoding failed (see reasons below)
- `attempted_queries`: Number of query variations attempted

### Failure Reasons

1. **`missing_fields`**
   - One or more required fields (address, city, state, zip) are empty
   - No geocoding attempt was made
   - `attempted_queries`: 0

2. **`no_result`**
   - All geocoding query strategies failed to return any result
   - Tried multiple query variations (full address, no-zip, territory, city-state)
   - `attempted_queries`: Number of strategies tried (typically 4)

3. **`coarse_skip`**
   - Only a city/state centroid was found (too coarse for routing)
   - Not precise enough for delivery/routing purposes
   - `attempted_queries`: Number of strategies tried before finding coarse match

4. **`cached_failure`**
   - Address was previously attempted and failed
   - Retrieved from cache to avoid repeated API calls
   - `attempted_queries`: 0 (already attempted in previous run)

## Output Files

### geocoded.csv
**Contains:** Only successfully geocoded addresses with valid lat/lon coordinates

**Columns:**
- `id`: Site ID
- `address`: Normalized address
- `lat`: Latitude (decimal degrees)
- `lon`: Longitude (decimal degrees)
- `display_name`: Full address from geocoding provider

### geocode-errors.csv
**Contains:** All addresses that failed to geocode for any reason

**Columns:** As described above

## Code Changes

### GeocodeWorker Class

**New tracking variables:**
```python
total_errors = 0  # Total count of failed geocoding attempts
error_rows = []   # List of error records per state
```

**Modified behavior:**
- Successful geocodes → added to `out_rows` → written to `geocoded.csv`
- Failed geocodes → added to `error_rows` → written to `geocode-errors.csv`
- Cache behavior unchanged: Failed attempts still cached with `source="none"`

**Updated signal:**
```python
finished = pyqtSignal(int, int, int, int)  # total_lookups, cache_hits, new_geocoded, total_errors
```

### GeocodeTab Class

**Updated handler:**
```python
def _on_worker_finished(self, total_lookups: int, cache_hits: int, 
                       new_geocoded: int, total_errors: int) -> None:
    # Displays: "Geocoding complete. Lookups: X, cache hits: Y, successful: Z, failed: W"
```

## Benefits

### 1. **Data Quality Visibility**
- Easily identify problematic addresses
- Spot patterns in failures (missing data, bad formatting, etc.)
- Prioritize data cleanup efforts

### 2. **Manual Correction Workflow**
1. Review `geocode-errors.csv`
2. Correct addresses in source data or manually geocode
3. Re-import corrected addresses
4. Re-run geocoding (corrected addresses will succeed)

### 3. **Performance Optimization**
- Failed attempts are cached to avoid repeated API calls
- Reduces wasted API quota on addresses that won't work
- Speeds up subsequent geocoding runs

### 4. **Audit Trail**
- Track which geocoding strategy was used
- Know how many query variations were attempted
- Understand why each address failed

## Example Error CSV

```csv
id,address,city,state,zip,normalized_address,strategy,reason,attempted_queries
1001,,"Springfield",IL,62701,,nominatim,missing_fields,0
1002,123 Main St,Springfield,IL,,"123 Main St, Springfield, IL , USA",nominatim,missing_fields,0
1003,456 Oak Ave,Nowhere,IL,99999,"456 Oak Ave, Nowhere, IL 99999, USA",nominatim,no_result,4
1004,789 Elm St,Chicago,IL,60601,"789 Elm St, Chicago, IL 60601, USA",nominatim,coarse_skip,4
1005,321 Pine Rd,Rockford,IL,61101,"321 Pine Rd, Rockford, IL 61101, USA",nominatim,cached_failure,0
```

## Logging Output

### Per-Address Logging

**Successful:**
```
State IL: [1/100] 1001 -> 41.234567,-87.654321 (nominatim:full)
State IL: [2/100] 1002 -> 42.123456,-88.765432 (cache)
```

**Failed:**
```
State IL: [3/100] 1003 -> no result (tried 4 queries)
State IL: [4/100] 1004 -> coarse match skipped (city/state only)
State IL: [5/100] 1005 -> cached failure (previously failed)
```

### Summary Logging

**Per-State:**
```
State IL: wrote 85 successful geocodes to <path>/geocoded.csv
State IL: wrote 15 failed geocodes to <path>/geocode-errors.csv
```

**Final Summary:**
```
Geocoding complete. Lookups: 100, cache hits: 30, successful: 85, failed: 15
```

## Testing

### Unit Tests
All existing strategy pattern tests pass (5/5):
- Strategy interface validation
- Nominatim initialization
- Google Maps stub
- Abstract base class enforcement

### Manual Testing Checklist
- [ ] Run geocoding on state with some bad addresses
- [ ] Verify `geocode-errors.csv` is created
- [ ] Verify error CSV has correct columns and data
- [ ] Verify `geocoded.csv` only contains successful geocodes
- [ ] Verify error count in final summary matches file
- [ ] Verify cached failures are handled correctly
- [ ] Test with missing_fields addresses
- [ ] Test with addresses that return no results
- [ ] Test cancellation during geocoding

## Future Enhancements

### 1. **Error Analysis Dashboard**
- Count errors by reason type
- Identify most common failure patterns
- Suggest data cleanup priorities

### 2. **Retry Failed Addresses**
- UI button to retry only failed addresses
- Skip cached failures or force re-attempt
- Track retry attempts

### 3. **Export Error Summary**
- Aggregate errors across all states
- Generate report with statistics
- Export to Excel for review

### 4. **Address Validation**
- Pre-validate addresses before geocoding
- Warn about likely failures
- Suggest corrections

### 5. **Alternative Geocoding Strategies**
- Try different providers for failed addresses
- Fallback chain: Nominatim → Google Maps → Manual
- Track which provider succeeded

## Notes

- Error CSV is only created if there are errors (empty states won't have error files)
- Cache behavior ensures failed addresses aren't repeatedly attempted
- Strategy name in error CSV allows tracking which provider was used
- Attempted queries count helps understand how hard the system tried
- Original address components preserved for manual correction workflow
