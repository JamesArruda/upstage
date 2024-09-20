# Copyright (C) 2024 by the Georgia Tech Research Institute (GTRI)

# Licensed under the BSD 3-Clause License.
# See the LICENSE file in the project root for complete license terms and disclaimers.
"""Geographical types and protocols."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

POSITION = tuple[float, float, float]
POSITIONS = list[POSITION]
LAT_LON_ALT = POSITION
LAT_LON = tuple[float, float]


class EarthProtocol(Protocol):
    """Protocol for defining an earth model interface."""

    def distance(
        self,
        loc1: LAT_LON,
        loc2: LAT_LON,
        units: str,
    ) -> float:
        """Get the distance between two lat/lon (degrees) points."""

    def bearing(
        self,
        loc1: LAT_LON,
        loc2: LAT_LON,
        units: str,
    ) -> float:
        """Get the distance between two lat/lon (degrees) points."""

    def distance_and_bearing(
        self,
        loc1: LAT_LON,
        loc2: LAT_LON,
        units: str,
    ) -> tuple[float, float]:
        """Get the distance between two lat/lon (degrees) points."""

    def point_from_bearing_dist(
        self,
        point: LAT_LON,
        bearing: float,
        distance: float,
        distance_units: str = "nmi",
    ) -> tuple[float, float]:
        """Get a lat/lon in degrees from a point, bearing, and distance."""

    def lla2ecef(
        self,
        locs: list[LAT_LON_ALT],
    ) -> list[tuple[float, float, float]]:
        """Get ECEF coordinates from lat lon alt."""

    def ecef2lla(
        self,
        locs: list[LAT_LON_ALT],
    ) -> list[tuple[float, float, float]]:
        """Get ECEF coordinates from lat lon alt."""

    def geo_linspace(
        self,
        start: LAT_LON,
        end: LAT_LON,
        num_segments: int,
    ) -> list[LAT_LON]:
        """Get evenly spaced coordinates between lat/lon pairs."""

    def geo_circle(
        self,
        center: LAT_LON,
        radius: float,
        radius_units: str,
        num_points: int,
    ) -> list[LAT_LON]:
        """Create a circle on a globe."""


@dataclass
class CrossingCondition:
    """Data about an intersection."""

    kind: str
    begin: LAT_LON_ALT
    end: LAT_LON_ALT | None = None


INTERSECTION_LOCATION_CALLABLE = Callable[
    [
        LAT_LON_ALT,
        LAT_LON_ALT,
        LAT_LON_ALT,
        float,
        str,
        EarthProtocol,
        float | None,
        list[int] | None,
    ],
    list[CrossingCondition],
]
