"""Pulling an address out of what the dispatcher typed.

A wrong address is worse than no address: it sends the whole investigation
somewhere else and every finding after it inherits the error silently. So this
is conservative, and when it cannot find one the CLI asks rather than guesses.
"""

from __future__ import annotations

import pytest

from ic.cli import extract_address


@pytest.mark.parametrize("text,expected", [
    ("Structure fire at 1001 Van Ness Avenue",
     "1001 Van Ness Avenue"),
    ("Structure fire at 1001 Van Ness Avenue, San Francisco",
     "1001 Van Ness Avenue, San Francisco"),
    # The clause after the city describes the patient, not the place. Keeping
    # it produced an address no geocoder could resolve, and the brief silently
    # collapsed to "location unverified".
    ("Cardiac arrest at 1001 Van Ness Avenue, San Francisco, patient unresponsive",
     "1001 Van Ness Avenue, San Francisco"),
    ("Fire at 1001 Van Ness Avenue, San Francisco. Possible occupants trapped.",
     "1001 Van Ness Avenue, San Francisco"),
    ("Gas leak at 3200 California Street, smell reported by several residents",
     "3200 California Street"),
    ("Collapse at 1 Dr Carlton B Goodlett Place, elderly male",
     "1 Dr Carlton B Goodlett Place"),
])
def test_the_address_is_extracted_without_the_narrative(text, expected):
    assert extract_address(text) == expected


def test_a_description_with_no_address_yields_nothing():
    assert extract_address("there is a lot of smoke somewhere downtown") is None


def test_a_bare_street_address_without_at_is_still_found():
    assert extract_address("smoke showing, 3200 California Street") == "3200 California Street"


def test_trailing_punctuation_is_trimmed():
    assert not (extract_address("Fire at 1001 Van Ness Avenue.") or "").endswith(".")
