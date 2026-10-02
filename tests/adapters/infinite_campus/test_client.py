"""The Infinite Campus roster export, against the fake IC.

The fake mirrors what made the real flow tricky (the XSRF form field,
the device confirmation page, calendar names with a school-year prefix,
the form-POST export), so these exercise the same requests production
makes.
"""

import pytest
from minnesota_immunization_mock.sample_data import roster_csv

from mn_immunization.adapters.infinite_campus.client import (
    IcError,
    IcLoginError,
    IcSite,
    ic_opener,
    ic_session,
)
from mn_immunization.records.roster import roster_rows

CALENDARS = {"2542": "FHMS", "2543": "GEMS", "2544": "PK", "9999": "NOPE"}


def site(mock_aisr, roster_filter="MIIC Oct 2023") -> IcSite:
    return IcSite(
        base_url=mock_aisr.ic_url, app_name="wstpaul", roster_filter=roster_filter
    )


def session(mock_aisr, password="ic_password", **kwargs):
    return ic_session(site(mock_aisr, **kwargs), "ic_user", password, CALENDARS)


def test_a_school_roster_comes_back_in_the_miic_layout(mock_aisr):
    with session(mock_aisr) as ic:
        roster = ic.export_roster("2542")

    assert roster == roster_csv("2542")
    assert roster_rows(roster) == 3
    assert mock_aisr.ic.exports == ["26-27FHMS"]


def test_the_device_is_never_registered(mock_aisr):
    # Trusting a device is the account owner's decision; every login
    # continues past the confirmation page for this session only.
    with session(mock_aisr) as ic:
        ic.export_roster("2543")

    assert mock_aisr.ic.devices_registered == 0


def test_a_calendar_code_matches_only_its_own_calendar(mock_aisr):
    # "PK" must find 26-27PK, not 26-27VPK-PK.
    with session(mock_aisr) as ic:
        ic.export_roster("2544")

    assert mock_aisr.ic.exports == ["26-27PK"]


def test_wrong_credentials_fail_at_login(mock_aisr):
    with pytest.raises(IcLoginError), session(mock_aisr, password="wrong"):
        pass


def test_an_unknown_calendar_or_filter_is_an_error_naming_it(mock_aisr):
    with session(mock_aisr) as ic, pytest.raises(IcError) as caught:
        ic.export_roster("9999")
    assert str(caught.value) == "calendar NOPE: 0 matches"

    with session(mock_aisr, roster_filter="Gone") as ic, pytest.raises(IcError):
        ic.export_roster("2542")


def test_a_failed_export_carries_the_status_never_the_body(mock_aisr):
    mock_aisr.ic.faults.export_status["26-27GEMS"] = 500

    with session(mock_aisr) as ic, pytest.raises(IcError) as caught:
        ic.export_roster("2543")

    assert caught.value.status_code == 500
    assert str(caught.value) == "HTTP 500 exporting the roster for school 2543"


def test_the_opener_reads_credentials_once(mock_aisr):
    reads = []

    def secret(name):
        reads.append(name)
        return {
            "infinite-campus-username": "ic_user",
            "infinite-campus-password": "ic_password",
        }[name]

    opener = ic_opener(secret, site(mock_aisr), CALENDARS)
    for _ in range(2):
        with opener():
            pass

    assert reads == ["infinite-campus-username", "infinite-campus-password"]
