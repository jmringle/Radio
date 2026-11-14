"""Running NEC2 through PyNEC.

NEC2 splits each wire into short segments and solves for the RF current on every one (the
"method of moments"); impedance, pattern and gain all follow from those currents.
"""

import math

from PyNEC import nec_context

SEGMENTS = 51  # odd, so one segment sits exactly at the center feedpoint


def dipole_impedance(mhz: float, length_m: float, radius_m: float) -> complex:
    """Feedpoint impedance (ohms) of a straight, center-fed dipole in free space."""
    for name, value in (("Frequency", mhz), ("Length", length_m), ("Wire radius", radius_m)):
        if not (math.isfinite(value) and value > 0):
            raise ValueError(f"{name} must be a positive number, got {value}")
    if radius_m >= length_m / SEGMENTS:
        raise ValueError(f"Wire radius {radius_m} m is too thick for a {length_m} m wire "
                         "(NEC2 models thin wires: each segment must be longer than the wire's radius)")
    half = length_m / 2
    context = nec_context()
    geometry = context.get_geometry()
    # Tag 1, along the y axis, centered on the origin.
    geometry.wire(1, SEGMENTS, 0, -half, 0, 0, half, 0, radius_m, 1.0, 1.0)
    context.geometry_complete(0)
    context.gn_card(-1, 0, 0, 0, 0, 0, 0, 0)  # no ground: free space
    context.ex_card(0, 1, SEGMENTS // 2 + 1, 0, 1.0, 0, 0, 0, 0, 0)  # 1 V source at the center segment
    context.fr_card(0, 1, mhz, 0)
    context.xq_card(0)  # run
    return complex(context.get_input_parameters(0).get_impedance()[0])
