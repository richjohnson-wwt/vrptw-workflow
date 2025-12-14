# Geocoding Strategy Pattern Refactoring

## Overview
Refactored the geocoding functionality in `app/tabs/geocode_tab.py` to use the **Strategy Design Pattern**, making it easy to switch between different geocoding providers (Nominatim, Google Maps, etc.).

## Changes Made

### 1. Created New Module: `app/geocoding/`
A new module containing the strategy pattern implementation:

- **`strategy.py`**: Abstract base class `GeocodingStrategy` defining the interface
  - `geocode(query: str) -> Optional[Dict[str, Any]]`: Main geocoding method
  - `get_source_name() -> str`: Returns provider identifier for cache
  - `get_rate_limit_delay() -> float`: Returns delay between requests

- **`nominatim.py`**: `NominatimStrategy` implementation
  - Moved existing Nominatim geocoding logic into this strategy
  - Handles email configuration for Nominatim usage policy
  - Built-in rate limiting (1.05 seconds between requests)
  - Supports street-level address matching with fallback logic

- **`google_maps.py`**: `GoogleMapsStrategy` stub (for future implementation)
  - Placeholder implementation with API key configuration
  - Documented rate limits and requirements
  - Raises `NotImplementedError` when called

### 2. Refactored `GeocodeWorker` Class
- **Constructor**: Now accepts `GeocodingStrategy` instance instead of email string
- **`_nominatim_geocode()` → `_geocode()`**: Renamed and simplified to use strategy
- **Rate limiting**: Uses `strategy.get_rate_limit_delay()` instead of hard-coded value
- **Cache source**: Uses `strategy.get_source_name()` for cache storage
- **Multi-strategy fallback**: Maintained existing logic (full address → no-zip → territory → city-state)

### 3. Refactored `GeocodeTab` Class
- **Strategy initialization**: Creates `NominatimStrategy` instance in `_start_geocoding()`
- **Worker instantiation**: Passes strategy to `GeocodeWorker` instead of email
- **Removed dead code**: Deleted unused `_nominatim_geocode()` method
- **Cleaned imports**: Removed unused `requests` import (now handled by strategies)

### 4. Testing
Created comprehensive unit tests in `tests/test_geocoding_strategy.py`:
- ✅ Strategy interface implementation
- ✅ Nominatim strategy initialization
- ✅ Google Maps strategy stub
- ✅ Abstract base class enforcement
- **All 5 tests passing**

## Benefits

### 1. **Flexibility**
Easy to switch between geocoding providers by changing the strategy instance:
```python
# Use Nominatim
strategy = NominatimStrategy(email="user@example.com")

# Use Google Maps (when implemented)
strategy = GoogleMapsStrategy(api_key="YOUR_API_KEY")
```

### 2. **Separation of Concerns**
- Each provider's logic is isolated in its own class
- Provider-specific configuration (email, API keys) is encapsulated
- Rate limiting is handled per-provider

### 3. **Testability**
- Easy to create mock strategies for unit testing
- Can test geocoding logic without making actual API calls
- Each strategy can be tested independently

### 4. **Maintainability**
- Adding new providers requires only creating a new strategy class
- No need to modify existing `GeocodeWorker` or `GeocodeTab` code
- Clear interface contract defined by abstract base class

### 5. **Backwards Compatibility**
- Cache structure unchanged (already had `source` field)
- Same file structure and behavior
- Existing Nominatim functionality preserved

## How to Add a New Geocoding Provider

1. Create a new strategy class in `app/geocoding/`:
```python
from .strategy import GeocodingStrategy

class NewProviderStrategy(GeocodingStrategy):
    def __init__(self, api_key: str):
        self.api_key = api_key
    
    def geocode(self, query: str) -> Optional[Dict[str, Any]]:
        # Implement geocoding logic
        pass
    
    def get_source_name(self) -> str:
        return "new_provider"
    
    def get_rate_limit_delay(self) -> float:
        return 0.1  # Provider-specific delay
```

2. Update `app/geocoding/__init__.py`:
```python
from .new_provider import NewProviderStrategy
__all__ = [..., "NewProviderStrategy"]
```

3. Use the new strategy in `GeocodeTab._start_geocoding()`:
```python
from app.geocoding import NewProviderStrategy
strategy = NewProviderStrategy(api_key="YOUR_KEY")
```

## Future Enhancements

### Configuration-Based Provider Selection
Currently hard-coded in `_start_geocoding()`. Could be enhanced with:
- Configuration file (e.g., `config.yaml`)
- Environment variables
- UI dropdown for provider selection

### Google Maps Implementation
Complete the `GoogleMapsStrategy.geocode()` method:
- Implement HTTP request to Google Maps Geocoding API
- Handle API responses and errors
- Parse location data into standard format

### Additional Providers
Consider adding support for:
- **Mapbox Geocoding API**
- **HERE Geocoding API**
- **Azure Maps**
- **OpenCage Geocoding API**

### Strategy Factory
Create a factory pattern for strategy instantiation:
```python
class GeocodingStrategyFactory:
    @staticmethod
    def create(provider: str, **config) -> GeocodingStrategy:
        if provider == "nominatim":
            return NominatimStrategy(email=config["email"])
        elif provider == "google_maps":
            return GoogleMapsStrategy(api_key=config["api_key"])
        # ...
```

## Files Modified
- `app/tabs/geocode_tab.py`: Refactored to use strategy pattern
- `app/geocoding/__init__.py`: New module initialization
- `app/geocoding/strategy.py`: New abstract base class
- `app/geocoding/nominatim.py`: New Nominatim implementation
- `app/geocoding/google_maps.py`: New Google Maps stub
- `tests/test_geocoding_strategy.py`: New unit tests

## Testing Checklist
- [x] Unit tests for strategy pattern (5/5 passing)
- [ ] Manual test: Geocode single state with Nominatim
- [ ] Manual test: Geocode all states with Nominatim
- [ ] Manual test: Verify cache hit/miss behavior
- [ ] Manual test: Test cancellation during geocoding
- [ ] Manual test: Verify multi-strategy fallback logic
- [ ] Manual test: Clear cache functionality

## Notes
- The existing cache structure already supports multiple providers via the `source` field
- Rate limiting is now provider-specific and configurable
- The multi-strategy fallback logic (trying different query formats) is preserved
- Email configuration for Nominatim is still required and stored in QSettings
