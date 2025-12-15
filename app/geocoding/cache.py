"""
Geocoding cache management using SQLite.

This module provides a thread-safe caching layer for geocoding results,
allowing multiple workers and UI components to share cached data.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Dict, Optional


class GeocodingCache:
    """
    Manages SQLite-based caching for geocoding results.
    
    The cache stores normalized addresses with their geocoding results,
    including latitude, longitude, display name, source provider, and
    timestamp. This prevents redundant API calls and improves performance.
    
    Thread-safe: Each operation opens its own connection, making it safe
    for use across multiple threads/workers.
    
    Attributes:
        cache_dir: Directory where the cache database is stored.
    """
    
    def __init__(self, cache_dir: Optional[Path] = None) -> None:
        """
        Initialize the geocoding cache.
        
        Args:
            cache_dir: Optional custom directory for cache storage.
                      If None, uses ~/Documents/VRPTW/.cache/
        """
        if cache_dir is None:
            cache_dir = Path.home() / "Documents" / "VRPTW" / ".cache"
        
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
    
    def get_cache_path(self) -> Path:
        """
        Get the full path to the cache database file.
        
        Returns:
            Path to the SQLite database file.
        """
        return self.cache_dir / "nominatim.sqlite"
    
    def connect(self) -> sqlite3.Connection:
        """
        Open a connection to the cache database and ensure schema exists.
        
        Creates the addresses table and index if they don't exist.
        
        Returns:
            SQLite connection object.
        """
        db_path = self.get_cache_path()
        conn = sqlite3.connect(str(db_path))
        cur = conn.cursor()
        
        # Create table if it doesn't exist
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS addresses (
              id INTEGER PRIMARY KEY,
              normalized_address TEXT UNIQUE,
              latitude REAL,
              longitude REAL,
              display_name TEXT,
              source TEXT,
              updated_at TEXT
            )
            """
        )
        
        # Create index for fast lookups
        cur.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_addresses_norm ON addresses(normalized_address)"
        )
        
        conn.commit()
        return conn
    
    def get(self, normalized_address: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve a cached geocoding result.
        
        Args:
            normalized_address: The normalized address string to lookup.
        
        Returns:
            Dictionary with keys: lat, lon, display_name, source, updated_at
            Returns None if address is not in cache.
        """
        conn = self.connect()
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT latitude, longitude, display_name, source, updated_at FROM addresses WHERE normalized_address = ?",
                (normalized_address,),
            )
            row = cur.fetchone()
            
            if row:
                return {
                    "lat": row[0],
                    "lon": row[1],
                    "display_name": row[2],
                    "source": row[3],
                    "updated_at": row[4],
                }
            return None
        finally:
            conn.close()
    
    def put(
        self,
        normalized_address: str,
        lat: Optional[float],
        lon: Optional[float],
        display_name: str,
        source: str = "nominatim",
    ) -> None:
        """
        Store a geocoding result in the cache.
        
        If the address already exists, it will be updated with new values.
        
        Args:
            normalized_address: The normalized address string as cache key.
            lat: Latitude (None for failed geocoding attempts).
            lon: Longitude (None for failed geocoding attempts).
            display_name: Human-readable address or error message.
            source: Name of the geocoding provider (e.g., "nominatim", "none").
        """
        conn = self.connect()
        try:
            cur = conn.cursor()
            cur.execute(
                "INSERT OR REPLACE INTO addresses (normalized_address, latitude, longitude, display_name, source, updated_at) VALUES (?, ?, ?, ?, ?, datetime('now'))",
                (normalized_address, lat, lon, display_name, source),
            )
            conn.commit()
        finally:
            conn.close()
    
    def clear_by_address(self, normalized_address: str) -> bool:
        """
        Clear a specific cache entry by its normalized address.
        
        Args:
            normalized_address: The exact normalized address to remove.
        
        Returns:
            True if entry was deleted, False if not found.
        """
        conn = self.connect()
        try:
            cur = conn.cursor()
            cur.execute(
                "DELETE FROM addresses WHERE normalized_address = ?",
                (normalized_address,),
            )
            deleted = cur.rowcount > 0
            conn.commit()
            return deleted
        finally:
            conn.close()
    
    def clear_by_addresses(self, normalized_addresses: list[str]) -> int:
        """
        Clear multiple specific cache entries.
        
        Args:
            normalized_addresses: List of normalized addresses to remove.
        
        Returns:
            Number of entries deleted.
        """
        if not normalized_addresses:
            return 0
        
        conn = self.connect()
        try:
            cur = conn.cursor()
            # Use parameterized query with IN clause
            placeholders = ",".join("?" * len(normalized_addresses))
            cur.execute(
                f"DELETE FROM addresses WHERE normalized_address IN ({placeholders})",
                normalized_addresses,
            )
            deleted = cur.rowcount
            conn.commit()
            return deleted
        finally:
            conn.close()
    
    def clear_by_state(self, state_code: str) -> int:
        """
        Clear cache entries for a specific state.
        
        Deletes all cached addresses that contain the state code in their
        normalized address string (e.g., "IL 62701" or ", IL ").
        
        Args:
            state_code: Two-letter state code (e.g., "IL", "CA").
        
        Returns:
            Number of entries deleted.
        """
        conn = self.connect()
        try:
            cur = conn.cursor()
            # Match addresses containing ", STATE " or " STATE zipcode"
            # This pattern should match our normalized format
            pattern = f"%, {state_code.upper()} %"
            cur.execute(
                "DELETE FROM addresses WHERE normalized_address LIKE ?",
                (pattern,),
            )
            deleted = cur.rowcount
            conn.commit()
            return deleted
        finally:
            conn.close()
    
    def get_cache_stats(self, state_code: Optional[str] = None) -> Dict[str, int]:
        """
        Get statistics about cached entries.
        
        Args:
            state_code: Optional state code to filter by (e.g., "IL").
        
        Returns:
            Dictionary with keys: total, successful, failed.
        """
        conn = self.connect()
        try:
            cur = conn.cursor()
            
            if state_code:
                pattern = f"%, {state_code.upper()} %"
                # Total entries for state
                cur.execute(
                    "SELECT COUNT(*) FROM addresses WHERE normalized_address LIKE ?",
                    (pattern,),
                )
                total = cur.fetchone()[0]
                
                # Successful entries (have lat/lon)
                cur.execute(
                    "SELECT COUNT(*) FROM addresses WHERE normalized_address LIKE ? AND latitude IS NOT NULL AND longitude IS NOT NULL",
                    (pattern,),
                )
                successful = cur.fetchone()[0]
            else:
                # Total entries
                cur.execute("SELECT COUNT(*) FROM addresses")
                total = cur.fetchone()[0]
                
                # Successful entries (have lat/lon)
                cur.execute(
                    "SELECT COUNT(*) FROM addresses WHERE latitude IS NOT NULL AND longitude IS NOT NULL"
                )
                successful = cur.fetchone()[0]
            
            failed = total - successful
            
            return {
                "total": total,
                "successful": successful,
                "failed": failed,
            }
        finally:
            conn.close()
    
    def clear(self) -> bool:
        """
        Clear the entire cache by deleting the database file.
        
        Returns:
            True if cache was cleared, False if cache file didn't exist.
        """
        cache_path = self.get_cache_path()
        if cache_path.exists():
            cache_path.unlink()
            return True
        return False
    
    @staticmethod
    def normalize_address(address: str, city: str, state: str, zip5: str) -> str:
        """
        Normalize an address into a consistent format for cache lookups.
        
        Creates a comma-separated string with non-empty components:
        "address, city, state zip, USA"
        
        Args:
            address: Street address.
            city: City name.
            state: State code.
            zip5: 5-digit ZIP code.
        
        Returns:
            Normalized address string.
        """
        parts = [address.strip(), city.strip(), f"{state.strip()} {zip5.strip()}", "USA"]
        return ", ".join([p for p in parts if p])
    
    def __enter__(self) -> GeocodingCache:
        """Context manager entry."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Context manager exit."""
        # No cleanup needed as connections are opened/closed per operation
        pass
