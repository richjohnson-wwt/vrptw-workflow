"""Google Maps geocoding strategy implementation (stub)."""

from typing import Any, Dict, Optional

from .strategy import GeocodingStrategy


class GoogleMapsStrategy(GeocodingStrategy):
    """Geocoding strategy using Google Maps Geocoding API.

    This is a stub implementation for future use.

    Requirements:
    - Google Maps API key with Geocoding API enabled
    - Billing account (Google charges per request after free tier)
    - See: https://developers.google.com/maps/documentation/geocoding

    Rate limits:
    - Default: 50 requests per second
    - Can be configured in Google Cloud Console
    """

    def __init__(self, api_key: str):
        """Initialize Google Maps strategy.

        Args:
            api_key: Google Maps API key
        """
        self.api_key = api_key
        self.base_url = "https://maps.googleapis.com/maps/api/geocode/json"

    def geocode(self, query: str) -> Optional[Dict[str, Any]]:
        """Geocode an address using Google Maps API.

        Args:
            query: Address string to geocode

        Returns:
            Dictionary with 'lat', 'lon', 'display_name' if successful, None otherwise
        """
        # TODO: Implement Google Maps geocoding
        # Example implementation:
        # params = {
        #     "address": query,
        #     "key": self.api_key,
        # }
        # resp = requests.get(self.base_url, params=params, timeout=10)
        # if resp.status_code == 200:
        #     data = resp.json()
        #     if data.get("status") == "OK" and data.get("results"):
        #         result = data["results"][0]
        #         location = result["geometry"]["location"]
        #         return {
        #             "lat": float(location["lat"]),
        #             "lon": float(location["lng"]),
        #             "display_name": result.get("formatted_address", ""),
        #         }
        # return None
        raise NotImplementedError("Google Maps geocoding not yet implemented")

    def get_source_name(self) -> str:
        """Get the provider name for cache storage.

        Returns:
            'google_maps'
        """
        return "google_maps"

    def get_rate_limit_delay(self) -> float:
        """Get the recommended delay between requests.

        Google Maps has a much higher rate limit (50 req/s default).
        A small delay is still recommended to be respectful.

        Returns:
            0.02 seconds (50 requests per second)
        """
        return 0.02
