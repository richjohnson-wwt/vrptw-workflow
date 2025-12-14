"""Abstract base class for geocoding strategies."""

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional


class GeocodingStrategy(ABC):
    """Abstract base class for geocoding service providers.
    
    Implementations should handle provider-specific logic including:
    - API authentication (API keys, email, etc.)
    - Rate limiting
    - Request formatting
    - Response parsing
    - Error handling
    """

    @abstractmethod
    def geocode(self, query: str) -> Optional[Dict[str, Any]]:
        """Geocode an address query.
        
        Args:
            query: Address string to geocode
            
        Returns:
            Dictionary with keys 'lat', 'lon', 'display_name' if successful,
            None if geocoding fails or no results found.
        """
        pass

    @abstractmethod
    def get_source_name(self) -> str:
        """Get the provider name for cache storage.
        
        Returns:
            String identifier for this geocoding provider (e.g., 'nominatim', 'google_maps')
        """
        pass

    @abstractmethod
    def get_rate_limit_delay(self) -> float:
        """Get the recommended delay between requests in seconds.
        
        Returns:
            Delay in seconds to wait between geocoding requests
        """
        pass
