"""Forecast rules (README acceptance criteria), on small made-up databases."""

from datetime import UTC, datetime, timedelta

import pytest

from band_privileges import LicenseClass, Mode, check
from ft8_forecast import Contact, Decode, forecast
from ft8_forecast.forecast import BANDS, MIN_DAYS, band_for, miles_between, parse_grid
from ft8_forecast.store import open_db, save_contacts, save_decodes

NEWEST = datetime(2026, 10, 25, 15, 30, tzinfo=UTC)
TWENTY = 14_074_000


def rx(when=NEWEST, dial=TWENTY, snr=-10, sender="N0CALL", grid=None) -> Decode:
    return Decode(when, dial, False, snr, sender, grid, f"CQ {sender} {when:%H%M%S} {snr}")


def tx(when=NEWEST, dial=TWENTY) -> Decode:
    return Decode(when, dial, True, 0, "N0CALL", None, f"CQ N0CALL AA00 {when:%H%M%S}")


@pytest.fixture
def conn(tmp_path):
    conn = open_db(tmp_path / "ft8cast.sqlite")
    yield conn
    conn.close()


def band(conn, name="20m", hour=15, my_grid=None):
    result = forecast.compute(conn, hour, my_grid)
    return next(b for b in result.bands if b.band == name)


def days_back(n, hour=15):
    return (NEWEST - timedelta(days=n)).replace(hour=hour)


# --- grid squares and distance ---

@pytest.mark.parametrize("text, square", [("FN31", "FN31"), ("fn31", "FN31"), (" FN31pr ", "FN31"),
                                          ("FN31PR45", "FN31"), ("AA00", "AA00"), ("RR99", "RR99")])
def test_parse_grid(text, square):
    assert parse_grid(text) == square


@pytest.mark.parametrize("text", ["", "FN3", "FN", "SA00", "FN31P", "FN31ZZ", "FN31PR4", "F N31", "ＦN31"])
def test_parse_grid_rejects(text):
    with pytest.raises(ValueError, match="isn't a grid square"):
        parse_grid(text)


@pytest.mark.parametrize("a, b, miles", [
    ("JJ00", "JJ00", 0),
    ("JJ00", "JJ01", 69),  # 1 degree of latitude = 69.1 mi
    ("JJ00", "JJ10", 138),  # 2 degrees of longitude at 0.5 N = 138.2 mi
    ("JP00", "JP10", 68),  # the same 2 degrees at 60.5 N (square centers): 138.2 x cos 60.5 = 68.0
])
def test_miles_between_square_centers(a, b, miles):
    assert miles_between(a, b) == miles == miles_between(b, a)


def test_farthest_possible_is_about_half_way_round():
    # AA00 and RR99 are near opposite poles; half the circumference is 12,437 mi.
    assert 12_000 < miles_between("AA00", "RR99") <= 12_437


# --- bands ---

@pytest.mark.parametrize("name, low, high", BANDS)
def test_band_edges_match_band_privileges(name, low, high):
    def any_privilege(hz):
        return check(hz, Mode.CW, LicenseClass.EXTRA).allowed
    assert any_privilege(low) and any_privilege(high)
    assert not any_privilege(low - 1) and not any_privilege(high + 1)


@pytest.mark.parametrize("dial, name", [(1_840_000, "160m"), (3_573_000, "80m"), (7_074_000, "40m"),
                                        (10_136_000, "30m"), (14_074_000, "20m"), (18_100_000, "17m"),
                                        (21_074_000, "15m"), (24_915_000, "12m"), (28_074_000, "10m")])
def test_every_band_has_general_data_at_its_ft8_frequency(dial, name):
    assert band_for(dial) == name


@pytest.mark.parametrize("dial", [
    14_010_000,  # 20 m, but General data starts at 14.025
    13_999_000,  # just below 20 m (seen in real data)
    30_000_000,  # outside HF (seen in real data)
    5_357_000,  # 60 m: not covered by band-privileges v1
    7_074_000 + 300_000,  # beyond 40 m
])
def test_frequencies_without_general_data_privileges_have_no_band(dial):
    assert band_for(dial) is None


# --- the window: 30 days up to the newest decode, at one hour ---

def test_no_decodes_gives_no_forecast(conn):
    save_contacts(conn, [Contact("N0CALL", NEWEST, TWENTY, None)])  # contacts alone aren't enough
    assert forecast.compute(conn, 15, None) is None


def test_window_ends_at_the_newest_decode_not_today(conn):
    # NEWEST is in the past; all 5 days still count, wherever "now" is.
    save_decodes(conn, [rx(days_back(n)) for n in range(5)])
    result = forecast.compute(conn, 15, None)
    assert result.newest == NEWEST.replace(tzinfo=None)
    assert band(conn).listening_days == 5


def test_window_is_30_days_exclusive_at_the_far_end(conn):
    edge = NEWEST - timedelta(days=30)
    save_decodes(conn, [rx(), rx(edge, sender="N0CALL/P"), rx(edge + timedelta(seconds=1), sender="N0CALL/M")])
    # The decode exactly 30 days back is out; one second later is in.
    assert band(conn).stations == 2


def test_only_the_requested_hour_counts(conn):
    on_hour = NEWEST.replace(minute=0, second=0)
    save_decodes(conn, [rx(on_hour), rx(on_hour - timedelta(seconds=1), sender="N0CALL/P"),
                        rx(on_hour.replace(minute=59, second=59), sender="N0CALL/M")])
    assert band(conn, hour=15).stations == 2  # 15:00:00 and 15:59:59
    assert band(conn, hour=14).stations == 1  # 14:59:59


# --- all hours (hour=None) ---

def test_all_hours_counts_every_hour_and_a_day_once(conn):
    save_decodes(conn, [rx(NEWEST.replace(hour=3)), rx(sender="N0CALL/P"), rx(NEWEST.replace(hour=23), sender="N0CALL/M")])
    stats = band(conn, hour=None)
    assert (stats.listening_days, stats.stations, stats.stations_per_day) == (1, 3, 3)
    assert forecast.compute(conn, None, None).hour is None


def test_all_hours_counts_a_station_once_per_day(conn):
    save_decodes(conn, [rx(NEWEST.replace(hour=3)), rx()])  # the same station at 03 and 15
    assert band(conn, hour=None).stations_per_day == 1


def test_all_hours_keeps_the_30_day_window(conn):
    edge = NEWEST - timedelta(days=30)
    save_decodes(conn, [rx(), rx(edge, sender="N0CALL/P"), rx(edge + timedelta(seconds=1), sender="N0CALL/M")])
    assert band(conn, hour=None).stations == 2


def test_all_hours_farthest_days_can_be_at_different_hours(conn):
    save_decodes(conn, [rx(grid="JJ10"), rx(days_back(1, hour=3), grid="JJ10")])
    assert band(conn, hour=None, my_grid="JJ00").farthest_miles == 138
    assert band(conn, hour=15, my_grid="JJ00").farthest_miles is None


def test_all_hours_counts_contacts_at_every_hour(conn):
    save_decodes(conn, [rx()])
    save_contacts(conn, [Contact("N0CALL", NEWEST.replace(hour=3), TWENTY, None), Contact("N0CALL/P", NEWEST, TWENTY, None),
                         Contact("N0CALL/M", NEWEST - timedelta(days=31), TWENTY, None)])
    assert band(conn, hour=None).contacts == 2


# --- what each column counts ---

def test_listening_days_count_dates_not_decodes(conn):
    save_decodes(conn, [rx(snr=s) for s in range(-20, -10)])
    assert band(conn).listening_days == 1


def test_a_tx_only_day_is_listening_with_zero_stations(conn):
    # Days 0-2: 1, 2 and 0 (Tx only) stations, so the median day is 1.
    save_decodes(conn, [rx(), rx(days_back(1)), rx(days_back(1), sender="N0CALL/P"), tx(days_back(2))])
    stats = band(conn)
    assert (stats.listening_days, stats.stations_per_day) == (3, 1)


def test_stations_per_day_is_the_median_day(conn):
    # 1, 1 and 10 stations on three days: a single busy day doesn't lift the typical one.
    busy = [rx(days_back(2), sender=f"N0CALL/{i}") for i in range(10)]
    save_decodes(conn, [rx(), rx(days_back(1)), *busy])
    assert band(conn).stations_per_day == 1


def test_stations_per_day_counts_distinct_senders_within_a_day(conn):
    save_decodes(conn, [rx(snr=s) for s in range(-20, -10)])  # one station, ten decodes
    assert band(conn).stations_per_day == 1


def test_stations_per_day_with_an_even_number_of_days_averages_the_middle_two(conn):
    save_decodes(conn, [rx(), rx(days_back(1)), rx(days_back(1), sender="N0CALL/P")])
    assert band(conn).stations_per_day == 1.5


def test_band_with_no_days_has_no_stations_per_day(conn):
    save_decodes(conn, [rx()])
    assert band(conn, "40m").stations_per_day is None


def test_stations_over_the_window_are_distinct_across_days(conn):
    save_decodes(conn, [rx(), rx(days_back(1)), rx(days_back(1), sender="N0CALL/P")])
    assert band(conn).stations == 2


def test_your_tx_lines_arent_stations_or_snr(conn):
    save_decodes(conn, [rx(snr=-15), tx()])
    stats = band(conn)
    assert (stats.stations, stats.median_snr) == (1, -15)


def test_stations_are_distinct_senders(conn):
    save_decodes(conn, [rx(snr=-1), rx(snr=-2), rx(sender="N0CALL/P"), rx(sender=None, snr=-3)])
    assert band(conn).stations == 2  # no-sender decodes still count for SNR, not stations


def test_median_snr(conn):
    save_decodes(conn, [rx(snr=s, sender=f"N{i}CALL") for i, s in enumerate([-20, -10, 5, -12])])
    assert band(conn).median_snr == -11


def two_days(sender="N0CALL", grid="JJ01", **kwargs):
    """The same station and grid decoded today and yesterday: enough to set Farthest."""
    return [rx(sender=sender, grid=grid, **kwargs), rx(days_back(1), sender=sender, grid=grid, **kwargs)]


def test_farthest_needs_my_grid(conn):
    save_decodes(conn, two_days())
    assert band(conn).farthest_miles is None
    assert band(conn, my_grid="JJ00").farthest_miles == 69


def test_farthest_is_the_maximum_and_names_its_grid(conn):
    save_decodes(conn, [*two_days("N0CALL", "JJ01"), *two_days("N0CALL/P", "JJ10"), rx(grid=None, snr=-3)])
    stats = band(conn, my_grid="JJ00")
    assert (stats.farthest_miles, stats.farthest_grid) == (138, "JJ10")


def test_farthest_ignores_a_station_heard_on_one_day_only(conn):
    # One day, however many decodes: could be a false decode or a passing fluke.
    one_day = [rx(sender="N0CALL/P", grid="JJ10", snr=s) for s in range(-20, -10)]
    save_decodes(conn, [*two_days("N0CALL", "JJ01"), *one_day])
    stats = band(conn, my_grid="JJ00")
    assert (stats.farthest_miles, stats.farthest_grid) == (69, "JJ01")


def test_farthest_needs_the_same_grid_on_both_days(conn):
    # One station, a different grid each day (a garbled decode, or moving): neither grid counts.
    save_decodes(conn, [rx(grid="JJ01"), rx(days_back(1), grid="JJ10")])
    assert band(conn, my_grid="JJ00").farthest_miles is None


def test_farthest_needs_the_same_station_on_both_days(conn):
    save_decodes(conn, [rx(sender="N0CALL", grid="JJ10"), rx(days_back(1), sender="N0CALL/P", grid="JJ10")])
    assert band(conn, my_grid="JJ00").farthest_grid is None


def test_farthest_days_must_be_at_this_hour_on_this_band(conn):
    save_decodes(conn, [rx(grid="JJ10"), rx(days_back(1, hour=14), grid="JJ10"),
                        rx(days_back(2), dial=7_074_000, grid="JJ10")])
    assert band(conn, my_grid="JJ00").farthest_miles is None


def test_bands_are_kept_apart(conn):
    save_decodes(conn, [rx(), rx(dial=7_074_000, sender="N0CALL/P")])
    assert (band(conn, "20m").stations, band(conn, "40m").stations) == (1, 1)


def test_decodes_without_general_data_privileges_are_ignored(conn):
    save_decodes(conn, [rx(), rx(dial=14_010_000, sender="N0CALL/P")])
    assert band(conn).stations == 1


def test_contacts_count_in_the_window_and_hour_only(conn):
    save_decodes(conn, [rx()])
    save_contacts(conn, [
        Contact("N0CALL", NEWEST, TWENTY, None),
        Contact("N0CALL/P", NEWEST.replace(hour=14), TWENTY, None),  # other hour
        Contact("N0CALL/M", NEWEST - timedelta(days=31), TWENTY, None),  # before the window
        Contact("N0CALL/QRP", NEWEST + timedelta(minutes=1), TWENTY, None),  # after newest decode
    ])
    assert band(conn).contacts == 1


@pytest.mark.parametrize("days, enough", [(MIN_DAYS - 1, False), (MIN_DAYS, True)])
def test_enough_data_needs_min_days(conn, days, enough):
    save_decodes(conn, [rx(days_back(n)) for n in range(days)])
    assert band(conn).enough_data is enough


def test_every_band_is_listed_low_to_high_even_with_no_data(conn):
    save_decodes(conn, [rx()])
    assert [b.band for b in forecast.compute(conn, 15, None).bands] == [name for name, _, _ in BANDS]



# --- farthest contact (ADIF): column, by day, ever ---

def contact(when=NEWEST, grid="JJ01", freq=TWENTY, call="N0CALL"):
    return Contact(call, when, freq, grid)


def test_farthest_contact_is_the_maximum_in_the_window_at_this_hour(conn):
    save_decodes(conn, [rx()])
    save_contacts(conn, [
        contact(grid="JJ01"), contact(days_back(1), grid="JJ10", call="N0CALL/P"),
        contact(NEWEST.replace(hour=14), grid="JJ20", call="N0CALL/M"),  # other hour
        contact(NEWEST - timedelta(days=31), grid="JJ30", call="N0CALL/QRP"),  # before the window
        contact(grid=None, call="N0CALL/B"),  # no grid logged
    ])
    stats = band(conn, my_grid="JJ00")
    assert (stats.contact_miles, stats.contact_grid) == (138, "JJ10")


def test_farthest_contact_needs_my_grid(conn):
    save_decodes(conn, [rx()])
    save_contacts(conn, [contact()])
    assert band(conn).contact_miles is None
    assert band(conn, my_grid="JJ00").contact_miles == 69


def test_farthest_contact_tie_goes_to_the_earlier(conn):
    # JJ01 and JJ0-1 (JI09) are both 69 mi from JJ00: the earlier contact's square is shown.
    save_decodes(conn, [rx()])
    save_contacts(conn, [contact(grid="JJ01"), contact(days_back(1), grid="JI09", call="N0CALL/P")])
    assert band(conn, my_grid="JJ00").contact_grid == "JI09"


def test_farthest_contact_ignores_frequencies_without_general_data(conn):
    save_decodes(conn, [rx()])
    save_contacts(conn, [contact(grid="JJ01"), contact(grid="JJ10", freq=14_010_000, call="N0CALL/P")])
    assert band(conn, my_grid="JJ00").contact_grid == "JJ01"


def test_farthest_contact_by_day_ignores_the_hour_newest_day_first(conn):
    save_decodes(conn, [rx()])
    save_contacts(conn, [
        contact(NEWEST.replace(hour=3), grid="JJ01"),
        contact(NEWEST.replace(hour=10), grid="JJ10", freq=7_074_000, call="N0CALL/P"),  # farther, other band
        contact(days_back(2), grid=None, call="N0CALL/M"),  # a day with no grid logged
        contact(NEWEST - timedelta(days=31), grid="JJ30", call="N0CALL/QRP"),  # before the window
    ])
    result = forecast.compute(conn, 15, "JJ00")
    assert result.daily == [forecast.Farthest("2026-10-25", "40m", 138, "JJ10"),
                            forecast.Farthest("2026-10-23", None, None, None)]


def test_farthest_contact_by_day_needs_my_grid(conn):
    save_decodes(conn, [rx()])
    save_contacts(conn, [contact()])
    assert forecast.compute(conn, 15, None).daily == []


def test_farthest_contact_ever_ignores_window_and_hour(conn):
    save_decodes(conn, [rx()])
    save_contacts(conn, [
        contact(grid="JJ01"),
        contact(NEWEST - timedelta(days=200, hours=12), grid="JJ30", call="N0CALL/P"),
        contact(NEWEST - timedelta(days=100), grid="JJ30", call="N0CALL/M"),  # a tie, later
        contact(NEWEST - timedelta(days=50), grid="RR99", freq=14_010_000, call="N0CALL/A"),  # no General data
    ])
    assert forecast.compute(conn, 15, "JJ00").best_ever == forecast.Farthest("2026-04-08", "20m", 415, "JJ30")


def test_no_farthest_contact_ever_without_a_gridded_contact_or_my_grid(conn):
    save_decodes(conn, [rx()])
    save_contacts(conn, [contact(grid=None)])
    assert forecast.compute(conn, 15, "JJ00").best_ever is None
    save_contacts(conn, [contact(grid="JJ01", call="N0CALL/P")])
    assert forecast.compute(conn, 15, None).best_ever is None
