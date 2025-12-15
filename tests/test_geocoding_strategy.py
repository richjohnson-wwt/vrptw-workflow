"""Tests for geocoding strategy pattern."""

import pytest

from app.geocoding import GeocodingStrategy, GoogleMapsStrategy, NominatimStrategy


def test_nominatim_strategy_initialization():
    """Test that NominatimStrategy initializes correctly."""
    email = "test@example.com"
    strategy = NominatimStrategy(email=email)

    assert strategy.email == email
    assert strategy.get_source_name() == "nominatim"
    # Rate limit delay is randomized between 1.0 and 1.5 seconds
    delay = strategy.get_rate_limit_delay()
    assert 1.0 <= delay <= 1.5, f"Rate limit delay {delay} should be between 1.0 and 1.5"


def test_nominatim_strategy_interface():
    """Test that NominatimStrategy implements GeocodingStrategy interface."""
    strategy = NominatimStrategy(email="test@example.com")

    assert isinstance(strategy, GeocodingStrategy)
    assert hasattr(strategy, "geocode")
    assert hasattr(strategy, "get_source_name")
    assert hasattr(strategy, "get_rate_limit_delay")


def test_google_maps_strategy_initialization():
    """Test that GoogleMapsStrategy initializes correctly."""
    api_key = "test_api_key"
    strategy = GoogleMapsStrategy(api_key=api_key)

    assert strategy.api_key == api_key
    assert strategy.get_source_name() == "google_maps"
    assert strategy.get_rate_limit_delay() == 0.02


def test_google_maps_strategy_not_implemented():
    """Test that GoogleMapsStrategy geocode raises NotImplementedError."""
    strategy = GoogleMapsStrategy(api_key="test_key")

    with pytest.raises(NotImplementedError):
        strategy.geocode("123 Main St, City, State")


def test_strategy_interface_is_abstract():
    """Test that GeocodingStrategy cannot be instantiated directly."""
    with pytest.raises(TypeError):
        GeocodingStrategy()
