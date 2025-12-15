import random
import re
import requests
from typing import Optional, Dict, Any, Callable

from .strategy import GeocodingStrategy

class NominatimStrategy(GeocodingStrategy):
    """
    Nominatim geocoding strategy tuned for real-world reliability.

    Design philosophy:
    - Be literal
    - Let Nominatim rank results
    - Filter AFTER geocoding, not before
    """

    def __init__(
        self,
        email: str,
        user_agent: str = "VRPTW-Workflow/0.1",
        logger: Optional[Callable[[str], None]] = None,
    ):
        self.email = email
        self.user_agent = user_agent
        self.base_url = "https://nominatim.openstreetmap.org/search"
        self.logger = logger or (lambda msg: None)

    # ------------------------------------------------------------------
    # Address cleaning (very conservative)
    # ------------------------------------------------------------------

    @staticmethod
    def _light_clean(address: str) -> str:
        """
        Only remove unit-level noise.
        Never remove building identifiers or floors.
        """
        patterns = [
            r",?\s*(?:suite|ste|unit|apt|apartment|room|rm)\.?\s*[#\w\d-]+",
            r",?\s*#\s*\d+",
        ]

        cleaned = address
        for pat in patterns:
            cleaned = re.sub(pat, "", cleaned, flags=re.IGNORECASE)

        cleaned = re.sub(r"\s+,", ",", cleaned)
        cleaned = re.sub(r"\s{2,}", " ", cleaned)
        return cleaned.strip()

    # ------------------------------------------------------------------
    # Core geocode method
    # ------------------------------------------------------------------

    def geocode(self, query: str) -> Optional[Dict[str, Any]]:
        """
        Progressive geocoding:
        1) cleaned query
        2) original query
        3) relaxed query (no ZIP)
        """

        attempts = [
            self._light_clean(query),
            query,
            self._strip_postal_code(query),
        ]

        seen = set()
        for attempt in attempts:
            if not attempt or attempt in seen:
                continue
            seen.add(attempt)

            result = self._single_geocode_attempt(attempt)
            if result:
                if attempt != query:
                    self.logger(f"Recovered using relaxed query: '{attempt[:60]}...'")
                return result

        self.logger(f"Nominatim failed all attempts for: {query[:60]}...")
        return None

    # ------------------------------------------------------------------
    # One HTTP request
    # ------------------------------------------------------------------

    def _single_geocode_attempt(self, query: str) -> Optional[Dict[str, Any]]:
        headers = {
            "User-Agent": f"{self.user_agent} (+{self.email})",
            "Accept-Language": "en",
        }

        params = {
            "q": query,
            "format": "jsonv2",
            "limit": 10,
            "addressdetails": 1,
        }

        try:
            resp = requests.get(
                self.base_url,
                headers=headers,
                params=params,
                timeout=10,
            )

            if resp.status_code == 429:
                self.logger("Nominatim rate limited (429)")
                return None

            if resp.status_code != 200:
                self.logger(
                    f"Nominatim HTTP {resp.status_code}: {resp.text[:120]}"
                )
                return None

            data = resp.json()
            if not data:
                return None

            return self._select_best_result(data)

        except requests.Timeout:
            self.logger("Nominatim timeout")
            return None
        except requests.RequestException as e:
            self.logger(f"Nominatim request error: {str(e)[:120]}")
            return None
        except (ValueError, KeyError) as e:
            self.logger(f"Nominatim parse error: {str(e)[:120]}")
            return None

    # ------------------------------------------------------------------
    # Result ranking (structure-based, not type-based)
    # ------------------------------------------------------------------

    def _select_best_result(self, results: list[dict]) -> Optional[Dict[str, Any]]:
        """
        Rank results by address structure, not Nominatim 'type'.
        """

        best_transport_no_number = None

        for item in results:
            lat = item.get("lat")
            lon = item.get("lon")
            addr = item.get("address", {})

            if not lat or not lon:
                continue

            # US only
            if addr.get("country_code") != "us":
                continue

            has_transport = any(
                key in addr for key in ("road", "pedestrian", "highway")
            )
            has_number = "house_number" in addr

            # Tier 1: true street address
            if has_transport and has_number:
                return {
                    "lat": float(lat),
                    "lon": float(lon),
                    "display_name": item.get("display_name", ""),
                }

            # Tier 2: highway / rural frontage
            if has_transport and not best_transport_no_number:
                best_transport_no_number = {
                    "lat": float(lat),
                    "lon": float(lon),
                    "display_name": item.get("display_name", ""),
                }

        # Tier 2 fallback
        if best_transport_no_number:
            return best_transport_no_number

        # Tier 3: last-resort US centroid
        for item in results:
            addr = item.get("address", {})
            if addr.get("country_code") == "us" and item.get("lat") and item.get("lon"):
                return {
                    "lat": float(item["lat"]),
                    "lon": float(item["lon"]),
                    "display_name": item.get("display_name", ""),
                }

        return None


    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _strip_postal_code(address: str) -> str:
        """Remove ZIP codes as a last-resort relaxation."""
        return re.sub(r"\b\d{5}(?:-\d{4})?\b", "", address).strip()

    def get_source_name(self) -> str:
        return "nominatim"

    def get_rate_limit_delay(self) -> float:
        # Add jitter to avoid fingerprinting
        return 1.05 + random.uniform(0.1, 0.3)
