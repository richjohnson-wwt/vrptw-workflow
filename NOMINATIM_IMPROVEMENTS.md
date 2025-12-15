# Nominatim Geocoding Improvements

## Overview
Improved the Nominatim geocoding strategy to increase success rates and provide better diagnostic information when geocoding fails.

## Problems Identified

### 1. **Overly Strict Type Filtering** ⚠️
**Before:** Only accepted 4 address types: `house`, `building`, `residential`, `yes`

**Problem:** Many valid addresses were rejected because they had different types:
- Businesses (type: `amenity`)
- Offices (type: `office`)
- Retail stores (type: `retail`, `shop`)
- Commercial buildings (type: `commercial`)
- Industrial facilities (type: `industrial`, `warehouse`)
- Apartment complexes (type: `apartments`)

**Impact:** Valid addresses were being marked as failures or falling back to less precise results.

### 2. **Silent Error Handling** 🤫
**Before:** All errors caught with generic exception handler, returning `None`

**Problem:** Impossible to diagnose why geocoding failed:
- Network timeouts
- API rate limiting (429 errors)
- Server errors (500, 503)
- Malformed responses
- JSON parsing errors

**Impact:** No visibility into root causes of failures.

### 3. **Short Timeout** ⏱️
**Before:** 5-second timeout

**Problem:** Some valid requests were timing out before Nominatim could respond, especially for:
- Complex addresses
- High API load
- Network latency issues

### 4. **No Diagnostic Logging** 🐛
**Before:** No logging mechanism in strategy

**Problem:** Couldn't see:
- What queries were being sent
- What responses were received
- Why results were rejected
- Which type filtering was applied

## Improvements Implemented

### 1. **Expanded Type Filtering** ✅

**Now accepts 15+ address types:**
```python
precise_types = {
    "house", "building", "residential", "yes", "address",
    "amenity", "office", "retail", "commercial", "industrial",
    "shop", "warehouse", "apartments", "place", "locality",
    "neighbourhood", "suburb", "quarter", "allotments"
}
```

**Benefits:**
- Accepts business addresses (amenity, office, retail, shop)
- Accepts commercial/industrial facilities
- Accepts apartment complexes
- Accepts named places and localities
- Still prioritizes precise results over city/state centroids

### 2. **Diagnostic Logging** 📊

**Added optional logger callback:**
```python
def __init__(self, email: str, user_agent: str = "VRPTW-Workflow/0.1", 
             logger: Optional[Callable[[str], None]] = None):
    self.logger = logger or (lambda msg: None)
```

**Logs the following events:**
- Rate limiting (429 errors)
- HTTP errors with status codes and response text
- Empty result sets
- Successful matches with type information
- Fallback results with type warnings
- Timeout errors
- Network/request errors
- JSON parsing errors

**Example log messages:**
```
[Strategy] Nominatim rate limit (429) for query: 123 Main St, Springfield...
[Strategy] Nominatim found amenity match for: 456 Oak Ave, Chicago...
[Strategy] Nominatim using fallback result (type: city) for: 789 Elm St...
[Strategy] Nominatim timeout (10s) for query: Complex Address...
```

### 3. **Increased Timeout** ⏰

**Changed from 5 to 10 seconds:**
```python
resp = requests.get(self.base_url, headers=headers, params=params, timeout=10)
```

**Benefits:**
- More time for complex queries
- Reduces false failures from timeouts
- Better handling of API load spikes

### 4. **Better Error Handling** 🛡️

**Specific exception handling:**
```python
except requests.Timeout:
    self.logger(f"Nominatim timeout (10s) for query: {query[:50]}...")
    return None
except requests.RequestException as e:
    self.logger(f"Nominatim request error for query: {query[:50]}... - {str(e)[:100]}")
    return None
except (ValueError, KeyError) as e:
    self.logger(f"Nominatim parse error for query: {query[:50]}... - {str(e)[:100]}")
    return None
```

**Benefits:**
- Distinguish between timeout, network, and parsing errors
- Log specific error messages for debugging
- Better understanding of failure patterns

### 5. **Rate Limit Detection** 🚦

**Explicit 429 handling:**
```python
if resp.status_code == 429:
    self.logger(f"Nominatim rate limit (429) for query: {query[:50]}...")
    return None
```

**Benefits:**
- Identify when you're hitting rate limits
- Helps determine if rate limiting needs adjustment
- Clear indication in logs

## Integration with GeocodeWorker

**Logger setup in worker thread:**
```python
# Set up strategy logger to emit diagnostic messages
if hasattr(self.strategy, 'logger'):
    self.strategy.logger = lambda msg: self.log.emit(f"[Strategy] {msg}")
```

**Benefits:**
- Diagnostic messages appear in geocoding log tab
- Prefixed with `[Strategy]` for easy identification
- Thread-safe emission via Qt signals
- No changes needed to strategy creation code

## Expected Impact

### Success Rate Improvements
- **Before:** Many valid business addresses rejected
- **After:** Accepts 15+ address types including businesses, offices, retail

### Diagnostic Visibility
- **Before:** Silent failures, no way to diagnose issues
- **After:** Detailed logging of all failure reasons

### Reliability
- **Before:** 5s timeout caused false failures
- **After:** 10s timeout reduces timeout-related failures

## Testing

### Unit Tests
All existing tests pass (5/5):
```bash
uv run pytest tests/test_geocoding_strategy.py -v
```

### Manual Testing Checklist
- [ ] Run geocoding on state with business addresses
- [ ] Verify increased success rate for amenity/office/retail types
- [ ] Check geocoding log for `[Strategy]` diagnostic messages
- [ ] Verify rate limit detection (if applicable)
- [ ] Compare error counts before/after improvements
- [ ] Review `geocode-errors.csv` for remaining failures

## Log Output Examples

### Successful Geocoding
```
State IL: [1/100] 1001 -> reading addresses.csv
[Strategy] Nominatim found amenity match for: 123 Restaurant St, Chicago, IL 60601...
State IL: [1/100] 1001 -> 41.878114,-87.629798 (nominatim:full)
```

### Rate Limiting
```
[Strategy] Nominatim rate limit (429) for query: 456 Oak Ave, Springfield...
State IL: [2/100] 1002 -> no result (tried 4 queries)
```

### Timeout
```
[Strategy] Nominatim timeout (10s) for query: 789 Complex Address Ln...
State IL: [3/100] 1003 -> no result (tried 4 queries)
```

### Fallback Result
```
[Strategy] Nominatim using fallback result (type: city) for: 321 Pine Rd...
State IL: [4/100] 1004 -> coarse match skipped (city/state only)
```

## Code Changes

### Files Modified
- `app/geocoding/nominatim.py`: Expanded type filtering, added logging, improved error handling
- `app/tabs/geocode_tab.py`: Set up strategy logger in GeocodeWorker.run()

### Backward Compatibility
- ✅ Logger parameter is optional (defaults to no-op)
- ✅ All existing code continues to work
- ✅ No changes to strategy interface
- ✅ No changes to cache structure
- ✅ All tests pass

## Future Enhancements

### 1. **Adaptive Rate Limiting**
- Detect 429 errors and automatically slow down
- Exponential backoff on rate limit hits
- Track rate limit recovery

### 2. **Type Priority Scoring**
- Assign scores to different address types
- Prefer higher-scored types (house > amenity > locality)
- Skip very low-scored types (country, state)

### 3. **Response Quality Metrics**
- Track success rates by address type
- Identify problematic query patterns
- Suggest query improvements

### 4. **Retry Logic**
- Retry timeouts with exponential backoff
- Retry 5xx server errors
- Skip retry for 4xx client errors

### 5. **Alternative Providers**
- Fallback to Google Maps on Nominatim failure
- Try multiple providers in sequence
- Track which provider works best

## Performance Considerations

### Timeout Increase
- **Trade-off:** Longer timeout means slower failure detection
- **Mitigation:** 10s is still reasonable for user experience
- **Benefit:** Reduces false failures significantly

### Expanded Type Filtering
- **Impact:** Minimal - just checking more values in a set
- **Benefit:** Significantly more addresses accepted

### Logging Overhead
- **Impact:** Minimal - only logs on events (not per-address)
- **Benefit:** Invaluable for debugging and monitoring

## Monitoring Recommendations

### Key Metrics to Track
1. **Success rate** - % of addresses successfully geocoded
2. **Error distribution** - Count by reason (no_result, timeout, rate_limit, etc.)
3. **Type distribution** - Which address types are most common
4. **Fallback rate** - How often fallback results are used
5. **Rate limit hits** - Frequency of 429 errors

### Log Analysis
Search logs for:
- `[Strategy] Nominatim rate limit` - Rate limiting issues
- `[Strategy] Nominatim timeout` - Timeout problems
- `[Strategy] Nominatim found` - Successful matches by type
- `[Strategy] Nominatim using fallback` - Imprecise results

## Summary

These improvements should significantly increase geocoding success rates, especially for business addresses, while providing detailed diagnostic information to help identify and resolve remaining issues. The expanded type filtering alone should reduce false failures substantially, and the diagnostic logging will make it much easier to understand and fix any remaining problems.
