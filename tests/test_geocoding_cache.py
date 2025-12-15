"""
Unit tests for the GeocodingCache class.
"""

import tempfile
from pathlib import Path

import pytest

from app.geocoding.cache import GeocodingCache


class TestGeocodingCache:
    """Test suite for GeocodingCache class."""

    def test_init_default_directory(self):
        """Test cache initialization with default directory."""
        cache = GeocodingCache()
        assert cache.cache_dir == Path.home() / "Documents" / "VRPTW" / ".cache"
        assert cache.cache_dir.exists()

    def test_init_custom_directory(self):
        """Test cache initialization with custom directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            custom_dir = Path(tmpdir) / "custom_cache"
            cache = GeocodingCache(cache_dir=custom_dir)
            assert cache.cache_dir == custom_dir
            assert cache.cache_dir.exists()

    def test_get_cache_path(self):
        """Test getting the cache database path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = GeocodingCache(cache_dir=Path(tmpdir))
            cache_path = cache.get_cache_path()
            assert cache_path == Path(tmpdir) / "nominatim.sqlite"
            assert cache_path.parent.exists()

    def test_connect_creates_schema(self):
        """Test that connect() creates the database schema."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = GeocodingCache(cache_dir=Path(tmpdir))
            conn = cache.connect()

            # Verify table exists
            cur = conn.cursor()
            cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='addresses'")
            assert cur.fetchone() is not None

            # Verify index exists
            cur.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_addresses_norm'"
            )
            assert cur.fetchone() is not None

            conn.close()

    def test_put_and_get_success(self):
        """Test storing and retrieving a successful geocoding result."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = GeocodingCache(cache_dir=Path(tmpdir))

            # Store a result
            norm_addr = "123 Main St, Springfield, IL 62701, USA"
            cache.put(norm_addr, 39.7817, -89.6501, "Springfield, IL", source="nominatim")

            # Retrieve it
            result = cache.get(norm_addr)
            assert result is not None
            assert result["lat"] == 39.7817
            assert result["lon"] == -89.6501
            assert result["display_name"] == "Springfield, IL"
            assert result["source"] == "nominatim"
            assert "updated_at" in result

    def test_put_and_get_failure(self):
        """Test storing and retrieving a failed geocoding attempt."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = GeocodingCache(cache_dir=Path(tmpdir))

            # Store a failed result
            norm_addr = "Invalid Address, Nowhere, XX 00000, USA"
            cache.put(norm_addr, None, None, "", source="none")

            # Retrieve it
            result = cache.get(norm_addr)
            assert result is not None
            assert result["lat"] is None
            assert result["lon"] is None
            assert result["display_name"] == ""
            assert result["source"] == "none"

    def test_get_nonexistent(self):
        """Test retrieving a non-existent address returns None."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = GeocodingCache(cache_dir=Path(tmpdir))
            result = cache.get("Nonexistent Address")
            assert result is None

    def test_put_updates_existing(self):
        """Test that put() updates an existing entry."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = GeocodingCache(cache_dir=Path(tmpdir))

            norm_addr = "123 Main St, Springfield, IL 62701, USA"

            # Store initial result
            cache.put(norm_addr, 39.0, -89.0, "Old Display", source="nominatim")

            # Update with new result
            cache.put(norm_addr, 39.7817, -89.6501, "New Display", source="nominatim")

            # Verify update
            result = cache.get(norm_addr)
            assert result["lat"] == 39.7817
            assert result["lon"] == -89.6501
            assert result["display_name"] == "New Display"

    def test_normalize_address(self):
        """Test address normalization."""
        # Normal case
        norm = GeocodingCache.normalize_address("123 Main St", "Springfield", "IL", "62701")
        assert norm == "123 Main St, Springfield, IL 62701, USA"

        # With extra whitespace
        norm = GeocodingCache.normalize_address(
            "  123 Main St  ", "  Springfield  ", "  IL  ", "  62701  "
        )
        assert norm == "123 Main St, Springfield, IL 62701, USA"

        # With empty components (should be filtered out)
        norm = GeocodingCache.normalize_address("123 Main St", "", "IL", "62701")
        assert norm == "123 Main St, IL 62701, USA"

    def test_clear_existing_cache(self):
        """Test clearing an existing cache."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = GeocodingCache(cache_dir=Path(tmpdir))

            # Create cache with data
            cache.put("Test Address", 1.0, 2.0, "Test", source="test")
            cache_path = cache.get_cache_path()
            assert cache_path.exists()

            # Clear cache
            result = cache.clear()
            assert result is True
            assert not cache_path.exists()

    def test_clear_nonexistent_cache(self):
        """Test clearing a non-existent cache."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = GeocodingCache(cache_dir=Path(tmpdir))

            # Don't create any data
            cache_path = cache.get_cache_path()
            assert not cache_path.exists()

            # Try to clear
            result = cache.clear()
            assert result is False

    def test_context_manager(self):
        """Test using cache as a context manager."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with GeocodingCache(cache_dir=Path(tmpdir)) as cache:
                cache.put("Test", 1.0, 2.0, "Test", source="test")
                result = cache.get("Test")
                assert result is not None

    def test_multiple_operations(self):
        """Test multiple cache operations in sequence."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = GeocodingCache(cache_dir=Path(tmpdir))

            # Store multiple addresses
            addresses = [
                ("Addr1", 1.0, 1.0, "Display1"),
                ("Addr2", 2.0, 2.0, "Display2"),
                ("Addr3", 3.0, 3.0, "Display3"),
            ]

            for addr, lat, lon, disp in addresses:
                cache.put(addr, lat, lon, disp, source="nominatim")

            # Retrieve and verify all
            for addr, lat, lon, disp in addresses:
                result = cache.get(addr)
                assert result is not None
                assert result["lat"] == lat
                assert result["lon"] == lon
                assert result["display_name"] == disp

    def test_thread_safety_simulation(self):
        """Test that each operation opens its own connection."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = GeocodingCache(cache_dir=Path(tmpdir))

            # Simulate multiple "threads" by performing operations sequentially
            # Each operation should open and close its own connection
            cache.put("Addr1", 1.0, 1.0, "Display1", source="nominatim")
            result1 = cache.get("Addr1")

            cache.put("Addr2", 2.0, 2.0, "Display2", source="nominatim")
            result2 = cache.get("Addr2")

            # Both should succeed
            assert result1 is not None
            assert result2 is not None
            assert result1["lat"] == 1.0
            assert result2["lat"] == 2.0

    def test_clear_by_address(self):
        """Test clearing a specific cache entry by address."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = GeocodingCache(cache_dir=Path(tmpdir))

            # Store multiple addresses
            cache.put("Addr1", 1.0, 1.0, "Display1", source="nominatim")
            cache.put("Addr2", 2.0, 2.0, "Display2", source="nominatim")
            cache.put("Addr3", 3.0, 3.0, "Display3", source="nominatim")

            # Clear one address
            result = cache.clear_by_address("Addr2")
            assert result is True

            # Verify it's gone
            assert cache.get("Addr2") is None

            # Verify others remain
            assert cache.get("Addr1") is not None
            assert cache.get("Addr3") is not None

    def test_clear_by_address_nonexistent(self):
        """Test clearing a non-existent address returns False."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = GeocodingCache(cache_dir=Path(tmpdir))
            result = cache.clear_by_address("Nonexistent")
            assert result is False

    def test_clear_by_addresses(self):
        """Test clearing multiple addresses at once."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = GeocodingCache(cache_dir=Path(tmpdir))

            # Store multiple addresses
            for i in range(5):
                cache.put(f"Addr{i}", float(i), float(i), f"Display{i}", source="nominatim")

            # Clear multiple
            deleted = cache.clear_by_addresses(["Addr1", "Addr3", "Addr4"])
            assert deleted == 3

            # Verify correct ones are gone
            assert cache.get("Addr0") is not None
            assert cache.get("Addr1") is None
            assert cache.get("Addr2") is not None
            assert cache.get("Addr3") is None
            assert cache.get("Addr4") is None

    def test_clear_by_addresses_empty_list(self):
        """Test clearing with empty list returns 0."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = GeocodingCache(cache_dir=Path(tmpdir))
            deleted = cache.clear_by_addresses([])
            assert deleted == 0

    def test_clear_by_state(self):
        """Test clearing cache entries for a specific state."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = GeocodingCache(cache_dir=Path(tmpdir))

            # Store addresses in different states
            cache.put(
                "123 Main St, Springfield, IL 62701, USA",
                39.78,
                -89.65,
                "Springfield, IL",
                source="nominatim",
            )
            cache.put(
                "456 Oak Ave, Chicago, IL 60601, USA",
                41.88,
                -87.63,
                "Chicago, IL",
                source="nominatim",
            )
            cache.put(
                "789 Pine Rd, Los Angeles, CA 90001, USA",
                34.05,
                -118.24,
                "Los Angeles, CA",
                source="nominatim",
            )
            cache.put(
                "321 Elm St, San Francisco, CA 94102, USA",
                37.77,
                -122.42,
                "San Francisco, CA",
                source="nominatim",
            )

            # Clear IL entries
            deleted = cache.clear_by_state("IL")
            assert deleted == 2

            # Verify IL entries are gone
            assert cache.get("123 Main St, Springfield, IL 62701, USA") is None
            assert cache.get("456 Oak Ave, Chicago, IL 60601, USA") is None

            # Verify CA entries remain
            assert cache.get("789 Pine Rd, Los Angeles, CA 90001, USA") is not None
            assert cache.get("321 Elm St, San Francisco, CA 94102, USA") is not None

    def test_clear_by_state_case_insensitive(self):
        """Test that state clearing is case-insensitive."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = GeocodingCache(cache_dir=Path(tmpdir))

            cache.put(
                "123 Main St, Springfield, IL 62701, USA",
                39.78,
                -89.65,
                "Springfield, IL",
                source="nominatim",
            )

            # Clear with lowercase
            deleted = cache.clear_by_state("il")
            assert deleted == 1

    def test_get_cache_stats_all(self):
        """Test getting cache statistics for all entries."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = GeocodingCache(cache_dir=Path(tmpdir))

            # Store successful and failed entries
            cache.put("Addr1", 1.0, 1.0, "Display1", source="nominatim")
            cache.put("Addr2", 2.0, 2.0, "Display2", source="nominatim")
            cache.put("Addr3", None, None, "", source="none")  # Failed
            cache.put("Addr4", None, None, "", source="none")  # Failed

            stats = cache.get_cache_stats()
            assert stats["total"] == 4
            assert stats["successful"] == 2
            assert stats["failed"] == 2

    def test_get_cache_stats_by_state(self):
        """Test getting cache statistics for a specific state."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = GeocodingCache(cache_dir=Path(tmpdir))

            # Store addresses in different states
            cache.put(
                "123 Main St, Springfield, IL 62701, USA",
                39.78,
                -89.65,
                "Springfield, IL",
                source="nominatim",
            )
            cache.put(
                "456 Oak Ave, Chicago, IL 60601, USA", None, None, "", source="none"
            )  # Failed
            cache.put(
                "789 Pine Rd, Los Angeles, CA 90001, USA",
                34.05,
                -118.24,
                "Los Angeles, CA",
                source="nominatim",
            )

            # Get stats for IL
            stats = cache.get_cache_stats(state_code="IL")
            assert stats["total"] == 2
            assert stats["successful"] == 1
            assert stats["failed"] == 1

            # Get stats for CA
            stats = cache.get_cache_stats(state_code="CA")
            assert stats["total"] == 1
            assert stats["successful"] == 1
            assert stats["failed"] == 0

    def test_get_cache_stats_empty(self):
        """Test getting cache statistics when cache is empty."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = GeocodingCache(cache_dir=Path(tmpdir))

            stats = cache.get_cache_stats()
            assert stats["total"] == 0
            assert stats["successful"] == 0
            assert stats["failed"] == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
