from datetime import datetime, timezone

import numpy as np

from ic7300 import mapdata, propagation

SOLAR_XML = """<?xml version="1.0"?><solar><solardata><source>N0NBH</source><updated> 31 Oct 2026 2317 GMT</updated>
<solarflux>92</solarflux><aindex> 26</aindex><kindex> 6</kindex><xray>A0.0</xray><sunspots>24</sunspots>
<solarwind>635.9</solarwind><geomagfield>MAJ STRM</geomagfield><calculatedconditions>
<band name="80m-40m" time="day">Poor</band><band name="30m-20m" time="day">Good</band>
<band name="80m-40m" time="night">Fair</band></calculatedconditions></solardata></solar>"""

PSK_XML = """<receptionReports><receptionReport receiverCallsign="K5TR" receiverLocator="EM00uf" senderCallsign="PY2XX"
senderLocator="GG66ab" frequency="14074023" flowStartSeconds="1793488397" mode="FT8" sNR="-12"/>
<receptionReport receiverCallsign="PY2XX" receiverLocator="GG66ab" senderCallsign="JA1ABC" senderLocator="PM95"
frequency="14074100" flowStartSeconds="1793488500" mode="FT8" sNR="3"/></receptionReports>"""


def test_parse_solar():
    s = propagation.parse_solar(SOLAR_XML)
    assert (s.sfi, s.a_index, s.k_index, s.sunspots) == (92, 26, 6, 24)
    assert s.condition_for("20m", True) == "Good"
    assert s.condition_for("40m", False) == "Fair"
    assert s.condition_for("6m", True) == ""


def test_parse_psk_and_endpoint():
    reports = propagation.parse_psk(PSK_XML)
    assert [r.snr for r in reports] == [-12, 3]
    lat, lon = propagation.report_endpoint(reports[0], "PY2XX")  # eu enviei -> a outra é o receptor (EM00)
    assert 30 < lat < 36 and -102 < lon < -96
    lat, lon = propagation.report_endpoint(reports[1], "PY2XX")  # eu recebi -> a outra é o emissor (PM95, Japão)
    assert 33 < lat < 38 and 135 < lon < 142


def test_sun_known_dates():
    # Solstício de junho: declinação perto de +23,4°; equinócio de março: perto de 0°
    dec, _ = mapdata.sun_position(datetime(2026, 6, 21, 12, tzinfo=timezone.utc))
    assert abs(dec - 23.4) < 0.3
    dec, _ = mapdata.sun_position(datetime(2026, 3, 20, 12, tzinfo=timezone.utc))
    assert abs(dec) < 0.6
    # Meio-dia UTC perto do equinócio: o Sol está a pino perto de lon ~0 (equação do tempo pequena)
    _, lon = mapdata.sun_position(datetime(2026, 3, 20, 12, tzinfo=timezone.utc))
    assert abs(lon) < 5
    assert mapdata.sun_elevation(0, 0, datetime(2026, 3, 20, 12, tzinfo=timezone.utc)) > 80
    assert mapdata.sun_elevation(0, 180, datetime(2026, 3, 20, 12, tzinfo=timezone.utc)) < -80


def test_darkness_grid_and_great_circle():
    g = mapdata.darkness_grid(datetime(2026, 3, 20, 12, tzinfo=timezone.utc))
    assert g.shape[0] == 91 and g.shape[1] == 181
    assert g[45, 90] == 0 and g[45, 0] == 1  # lon 0 dia, lon -180 noite (no equador)
    lon, lat = mapdata.great_circle(-23.3, -47.3, 35.7, 139.7, 80)  # Itu -> Tóquio cruza o antimeridiano
    assert np.isnan(lon).any()
    assert abs(lat[0] + 23.3) < 0.1
    xs, ys = mapdata.load_lines("borders")
    assert len(xs) == len(ys) > 1000
