"""Geocoding is cached, so a warmed address survives the network.

Found live: Nominatim's DNS stopped resolving for a minute. The survey was
cached but the geocode was not, so the location came back unverified, every
downstream lookup was skipped, and the whole run refused — correct behaviour,
and a demo that dies on someone else's outage.

A warmed address should be immune to that. Addresses do not move.
"""

from __future__ import annotations

import pytest

from ic.geo import Point
from ic.tools import maps


def test_a_geocode_is_cached_after_the_first_lookup(tmp_path, monkeypatch):
    monkeypatch.setattr(maps, "GEOCODE_CACHE_DIR", tmp_path)
    calls = []

    def fake_get(url):
        calls.append(url)
        return [{"lat": "37.7849", "lon": "-122.4219",
                 "display_name": "1001 Van Ness Avenue", "type": "building",
                 "importance": 0.6}]

    monkeypatch.setattr(maps, "_get", fake_get)
    first = maps.geocode("1001 Van Ness Avenue")
    second = maps.geocode("1001 Van Ness Avenue")
    assert first.ok and second.ok
    assert len(calls) == 1, "the second lookup should not reach the network"


def test_the_cached_result_carries_the_same_point(tmp_path, monkeypatch):
    monkeypatch.setattr(maps, "GEOCODE_CACHE_DIR", tmp_path)
    monkeypatch.setattr(maps, "_get", lambda url: [
        {"lat": "37.7849", "lon": "-122.4219", "display_name": "X",
         "type": "building", "importance": 0.6}])
    first = maps.geocode("somewhere")
    monkeypatch.setattr(maps, "_get", lambda url: (_ for _ in ()).throw(
        OSError("network down")))
    second = maps.geocode("somewhere")
    assert second.ok
    assert second.data["located"].point == first.data["located"].point


def test_a_warmed_address_survives_the_network_going_away(tmp_path, monkeypatch):
    monkeypatch.setattr(maps, "GEOCODE_CACHE_DIR", tmp_path)
    monkeypatch.setattr(maps, "_get", lambda url: [
        {"lat": "1.0", "lon": "2.0", "display_name": "Y", "type": "b",
         "importance": 0.5}])
    maps.geocode("warm address")

    monkeypatch.setattr(maps, "_get", lambda url: (_ for _ in ()).throw(
        OSError("nodename nor servname provided")))
    assert maps.geocode("warm address").ok


def test_a_cold_address_still_fails_honestly_when_the_network_is_down(tmp_path, monkeypatch):
    # Caching must not turn an unknown address into a pretend success.
    monkeypatch.setattr(maps, "GEOCODE_CACHE_DIR", tmp_path)
    monkeypatch.setattr(maps, "_get", lambda url: (_ for _ in ()).throw(
        OSError("network down")))
    with pytest.raises(OSError):
        maps.geocode("never seen before")


def test_a_failed_geocode_is_not_cached_as_a_result(tmp_path, monkeypatch):
    # "No match" must stay re-checkable — an address absent from OSM today may
    # be added tomorrow, and caching the absence would hide that forever.
    monkeypatch.setattr(maps, "GEOCODE_CACHE_DIR", tmp_path)
    monkeypatch.setattr(maps, "_get", lambda url: [])
    assert not maps.geocode("999999 Unknown Avenue").ok
    assert list(tmp_path.iterdir()) == []
