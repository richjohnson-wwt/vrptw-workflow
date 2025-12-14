"""Nominatim geocoding strategy implementation."""

from typing import Any, Dict, Optional

import requests

from .strategy import GeocodingStrategy


class NominatimStrategy(GeocodingStrategy):
    """Geocoding strategy using OpenStreetMap's Nominatim service.
    
    Nominatim is a free geocoding service with usage policies:
    - Maximum 1 request per second
    - Must provide valid User-Agent and email contact
    - See: https://operations.osmfoundation.org/policies/nominatim/
    """

    def __init__(self, email: str, user_agent: str = "VRPTW-Workflow/0.1"):
        """Initialize Nominatim strategy.
        
        Args:
            email: Contact email for Nominatim usage policy compliance
            user_agent: User agent string for requests
        """
        self.email = email
        self.user_agent = user_agent
        self.base_url = "https://nominatim.openstreetmap.org/search"

    def geocode(self, query: str) -> Optional[Dict[str, Any]]:
        """Geocode an address using Nominatim.
        
        Args:
            query: Address string to geocode
            
        Returns:
            Dictionary with 'lat', 'lon', 'display_name' if successful, None otherwise
        """
        headers = {
            "User-Agent": f"{self.user_agent} (+{self.email})",
            "Accept-Language": "en",
        }
        params = {
            "q": query,
            "format": "jsonv2",
            "limit": 5,
            "addressdetails": 1,
            # Include US and territories commonly present in client data
            "countrycodes": "us,pr,gu,vi,mp,as",
        }

        try:
            resp = requests.get(self.base_url, headers=headers, params=params, timeout=5)

            if resp.status_code != 200:
                # Could log: resp.status_code + resp.text[:200]
                return None

            data = resp.json()
            if not data:
                return None

            # Pick the best street-level match
            for item in data:
                if item.get("lat") and item.get("lon"):
                    if item.get("type") in ("house", "building", "residential", "yes"):
                        return {
                            "lat": float(item["lat"]),
                            "lon": float(item["lon"]),
                            "display_name": item.get("display_name", ""),
                        }

            # Fallback: first valid lat/lon
            top = data[0]
            return {
                "lat": float(top["lat"]),
                "lon": float(top["lon"]),
                "display_name": top.get("display_name", ""),
            }

        except (ValueError, KeyError, requests.RequestException):
            return None

    def get_source_name(self) -> str:
        """Get the provider name for cache storage.
        
        Returns:
            'nominatim'
        """
        return "nominatim"

    def get_rate_limit_delay(self) -> float:
        """Get the recommended delay between requests.
        
        Nominatim requires at least 1 second between requests.
        We use 1.05 seconds to be safe.
        
        Returns:
            1.05 seconds
        """
        return 1.05
