"""Bearings to a location. Two steps:

1. Sweep fit: the level at several headings from one spot, fitted to a yagi-like pattern, gives
   that spot's bearing with an uncertainty (+/- degrees) instead of "where the number peaked".
2. Probability map: each spot's bearing is a fuzzy wedge; multiplying the wedges over a grid
   shows where the fox probably is and how big the search area still is. A bearing that disagrees
   with the others (usually a reflection off a building or hill) is flagged and left out.

Flat-earth math around the spots: fine for a hunt a few km across, wrong past about 50 km."""
import math

import numpy as np

# --- sweep fit ---

MIN_MARKS = 4  # three unknowns (heading, strength, beam sharpness) need at least one spare point
SHARPNESS = np.array([1, 2, 3, 5, 8, 12, 20])  # cardioid powers: beamwidth from 180 degrees down to about 50
BACK_FLOOR_DB = -20.0  # a real yagi's back and sides don't go deeper than this
STEP_DEG = 0.5
SIGMA_FLOOR_DB = 1.0  # readings jitter by about this much even on a perfect sweep
MIN_PM_DEG = 3.0  # typed compass headings and aiming aren't better than a few degrees
ASSUMED_PM_DEG = 15.0  # a single pointed bearing, accuracy not measured
GIVE_UP_DEG = 90.0  # an uncertainty this wide means the sweep didn't pin anything down


def _wrap(deg):
    """Angle difference into -180..180."""
    return (np.asarray(deg) + 180.0) % 360.0 - 180.0


MIN_SPAN_DB = 3.0  # a yagi's front is usually 10+ dB over its back: flatter means mostly reflections or noise


def _bracketed(headings: np.ndarray, levels: np.ndarray) -> bool:
    """A weaker mark on each side of the strongest, so the peak lies inside the sweep."""
    if levels.max() - levels.min() < MIN_SPAN_DB:
        return False
    offsets = _wrap(headings - headings[np.argmax(levels)])
    weaker = levels < levels.max()
    return bool((weaker & (offsets > 0)).any() and (weaker & (offsets < 0)).any())


def fit_sweep(points: list[tuple[float, float]]) -> dict | None:
    """(heading, level dB) pairs from one spot -> {"heading", "pm"}, or None if they can't pin a bearing."""
    if len(points) < MIN_MARKS:
        return None
    headings = np.array([p[0] for p in points], dtype=float)
    levels = np.array([p[1] for p in points], dtype=float)
    if not _bracketed(headings, levels):
        return None
    centers = np.arange(0.0, 360.0, STEP_DEG)
    off = np.radians(headings[None, :] - centers[:, None])  # (center, mark)
    with np.errstate(divide="ignore"):
        shape_db = 10 * np.log10((1 + np.cos(off)) / 2)  # cardioid, 0 dB straight ahead
    pattern = np.maximum(SHARPNESS[:, None, None] * shape_db[None], BACK_FLOOR_DB)  # (k, center, mark)
    residual = levels - pattern
    residual -= residual.mean(axis=2, keepdims=True)  # best overall strength for each (k, center)
    sse = (residual ** 2).sum(axis=2).min(axis=0)  # best sharpness for each center
    best = int(np.argmin(sse))
    # Approximate 68% range: centers whose fit is worse by less than one reading's variance.
    variance = max(sse[best] / (len(points) - 3), SIGMA_FLOOR_DB ** 2)
    limit = sse[best] + variance
    reach = []
    for direction in (1, -1):
        steps = 0
        while sse[(best + direction * (steps + 1)) % len(centers)] <= limit:
            steps += 1
            if steps * STEP_DEG >= GIVE_UP_DEG:
                return None
        reach.append(steps * STEP_DEG)
    return {"heading": round(float(centers[best]), 1), "pm": round(max(max(reach), MIN_PM_DEG), 1)}


def spot_bearing(marks: list[dict]) -> dict | None:
    """A spot's bearing from its marks: fitted when the sweep allows, else the strongest mark."""
    if not marks:
        return None
    fit = fit_sweep([(m["heading"], m["level_db"]) for m in marks])
    if fit:
        return {**fit, "method": f"fitted from {len(marks)} headings"}
    strongest = max(marks, key=lambda m: m["level_db"])
    why = "strongest mark" if len(marks) == 1 else "strongest mark (sweep too narrow or lopsided to fit)"
    return {"heading": strongest["heading"], "pm": ASSUMED_PM_DEG, "method": f"{why}; ± assumed"}


def summarize(spots: list[dict], bearings: list[dict]) -> list[dict]:
    """Spots with their marks and bearing, for the page and the map."""
    out = []
    for spot in spots:
        marks = [b for b in bearings if b["spot"] == spot["id"]]
        out.append({**spot, "marks": marks, "bearing": spot_bearing(marks)})
    return out


# --- probability map ---

EARTH_M = 6_371_000.0
GRID = 160  # cells per side
MIN_HALF_M, MAX_HALF_M = 2_000.0, 50_000.0
OUTLIER_SHARE = 0.1  # chance any one bearing is simply wrong (a reflection): keeps one from vetoing the rest
FLAG_MIN_DEG = 20.0
MIN_TO_FLAG = 4  # with 3 spots, any one could be the odd one out: every pair of lines crosses somewhere
MAP_NEEDS = "Needs bearings from 2 or more spots with positions."


def _to_xy(lat, lon, lat0, lon0):
    """Meters east and north of (lat0, lon0)."""
    x = math.radians(lon - lon0) * EARTH_M * math.cos(math.radians(lat0))
    y = math.radians(lat - lat0) * EARTH_M
    return x, y


def _to_latlon(x, y, lat0, lon0):
    return (lat0 + math.degrees(y / EARTH_M),
            lon0 + math.degrees(x / (EARTH_M * math.cos(math.radians(lat0)))))


def _log_likelihood(xs, ys, spots):
    """Sum over spots of log P(that spot's bearing | fox in each cell)."""
    total = np.zeros_like(xs)
    for s in spots:
        toward = np.degrees(np.arctan2(xs - s["x"], ys - s["y"]))  # compass bearing from the spot to each cell
        miss = _wrap(toward - s["heading"])
        sigma = s["pm"]
        wedge = np.exp(-0.5 * (miss / sigma) ** 2) / (sigma * math.sqrt(2 * math.pi))
        total += np.log((1 - OUTLIER_SHARE) * wedge + OUTLIER_SHARE / 360.0)
    return total


def probability_map(summaries: list[dict]) -> dict:
    """The page's map: grid (0-255, row 0 = north), spots in meters, estimate, 90% search area, flags."""
    usable = [{"id": s["id"], "lat": s["lat"], "lon": s["lon"], **s["bearing"]}
              for s in summaries if s["lat"] is not None and s["bearing"]]
    if len(usable) < 2:
        return {"estimate": None, "text": MAP_NEEDS, "spots": [], "reflections": []}
    lat0 = sum(s["lat"] for s in usable) / len(usable)
    lon0 = sum(s["lon"] for s in usable) / len(usable)
    for s in usable:
        s["x"], s["y"] = _to_xy(s["lat"], s["lon"], lat0, lon0)
    spread = max(math.hypot(s["x"], s["y"]) for s in usable)
    half = min(max(MIN_HALF_M, 3 * spread), MAX_HALF_M)
    cell = 2 * half / GRID
    axis = -half + cell * (np.arange(GRID) + 0.5)
    xs, ys = np.meshgrid(axis, axis[::-1])  # row 0 is the north edge

    def best_cell(spots):
        ll = _log_likelihood(xs, ys, spots)
        row, col = np.unravel_index(int(np.argmax(ll)), ll.shape)
        return ll, row, col

    reflections = []
    if len(usable) >= MIN_TO_FLAG:
        _, row, col = best_cell(usable)
        fx, fy = xs[row, col], ys[row, col]
        for s in usable:
            miss = abs(float(_wrap(math.degrees(math.atan2(fx - s["x"], fy - s["y"])) - s["heading"])))
            if miss > max(3 * s["pm"], FLAG_MIN_DEG):
                reflections.append(s["id"])
        if len(usable) - len(reflections) < 3:
            reflections = []  # no clear majority agreeing: don't call anything a reflection
    kept = [s for s in usable if s["id"] not in reflections]
    ll, row, col = best_cell(kept)
    p = np.exp(ll - ll.max())
    p /= p.sum()
    ordered = np.sort(p, axis=None)[::-1]
    cells_90 = int(np.searchsorted(np.cumsum(ordered), 0.9)) + 1
    area_km2 = cells_90 * cell * cell / 1e6
    lat, lon = _to_latlon(float(xs[row, col]), float(ys[row, col]), lat0, lon0)
    at_edge = row in (0, GRID - 1) or col in (0, GRID - 1)
    text = f"Most likely spot {lat:.5f}, {lon:.5f}; 90% search area {area_km2:.2f} km²."
    if reflections:
        text += f" Left out as likely reflections: spot {', '.join(map(str, reflections))}."
    if at_edge:
        text += " The estimate is at the edge of the map: the fox may be farther away."
    return {
        "estimate": {"lat": round(lat, 5), "lon": round(lon, 5)},
        "area_km2": round(area_km2, 3),
        "reflections": reflections,
        "at_edge": at_edge,
        "half_m": half,
        "grid": np.round(p / p.max() * 255).astype(int).ravel().tolist(),
        "size": GRID,
        "spots": [{"id": s["id"], "x": round(s["x"], 1), "y": round(s["y"], 1), "heading": s["heading"],
                   "pm": s["pm"], "reflection": s["id"] in reflections} for s in usable],
        "text": text,
    }
