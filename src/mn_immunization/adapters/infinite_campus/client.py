"""Infinite Campus: the workflow's RosterSource, through the staff web app.

IC offers no API for ad hoc exports (OneRoster is read-only and knows
nothing of the district's roster filter), so this makes the same plain
HTTP requests the Data Export wizard makes:

1. Log in: GET `<app>.jsp` for the XSRF cookie, then POST `verify.jsp`. IC
   then shows a User Device Confirmation page for an unrecognized device;
   it is continued *without* recognizing the device. Each login emails
   the account owner, and trusting a device is a human's decision.
2. Find the district's saved roster filter by name, and each school's
   calendar by its code (config's "FHMS" matches "26-27FHMS", so the
   school-year prefix rolls over without a config change).
3. Export: a form POST to the delimited extract for that calendar,
   pipe-delimited with a header. The filter is built to produce MIIC's
   bulk-query layout.

Read-only: nothing here changes anything in IC. Errors say what was
attempted and carry an HTTP status, never a response body.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from mn_immunization.workflow.ports import RosterSourceOpener

logger = logging.getLogger(__name__)

TIMEOUT = (10, 60)
EXPORT_TIMEOUT = (10, 300)
TRANSIENT_STATUSES = frozenset({502, 503, 504})

WIZARD = (
    "adhoc/dataWizard/dataWizard.xsl?filters=1&x=dataWarehouse.WarehouseSettings"
    "&x=calendar.Calendar-schoolCalendar&objRights=adhoc.exportWizard"
    "&x=user.Outline-getToolRightsSkipCal&toolCode=adhoc.query"
    "&x=user.ToolUsageLog-logAccess"
)
FILTERS = (
    "adhoc/filters/filterList.xsl?x=dataWarehouse.WarehouseSettings&filters=1"
    "&base=&mode=dataWizard&type=adHocExport&nodeID=&objRights="
    "&x=user.Outline-getToolRightsSkipCal&toolCode=adhoc.query&ignoreHelpTool=true"
)
EXPORT = (
    "extract/adhocDelimited.xsl?&delimiter=pipe&doubleQuote=delimiter&showHeader=1"
    "&contentType=csv&includeAggregates=&x=adhoc.AdHocFilter-listAdhocData"
    "&filterID={filter_id}&source=live&saveAs=roster.csv"
)


class IcError(Exception):
    """An Infinite Campus request failed. `status_code` is the HTTP status
    when there was a response. The message never includes a body."""

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class IcLoginError(IcError):
    """Not logged in afterwards: wrong credentials, a changed login flow, or
    an account without Data Export rights."""


def _is_transient(error: BaseException) -> bool:
    if isinstance(
        error, (requests.exceptions.Timeout, requests.exceptions.ConnectionError)
    ):
        return True
    return isinstance(error, IcError) and error.status_code in TRANSIENT_STATUSES


# Read-only calls only: a few attempts on timeouts, connection errors, and
# 502/503/504. The login is not retried (each one emails the account owner).
_transient_retry = retry(
    stop=stop_after_attempt(4),
    wait=wait_exponential(multiplier=2, min=4, max=30),
    retry=retry_if_exception(_is_transient),
    reraise=True,
)


@dataclass(frozen=True)
class IcSite:
    """The district's Infinite Campus, from config."""

    base_url: str  # e.g. https://<district>.infinitecampus.org/campus
    app_name: str  # the district's login app, e.g. "wstpaul"
    roster_filter: str  # the saved ad hoc filter that produces MIIC rosters


@dataclass
class IcClient:
    session: requests.Session
    site: IcSite
    calendars: Mapping[str, str]  # school id -> its calendar code ("FHMS")
    calendar_ids: dict[str, str]  # calendar name ("26-27FHMS") -> IC id
    _filter_id: str | None = field(default=None, init=False)

    def export_roster(self, school_id: str) -> str:
        """The school's roster through the district's filter: MIIC's
        bulk-query layout, pipe-delimited, with a header."""
        calendar_id = self._calendar_id(self.calendars[school_id])
        url = urljoin(f"{_base(self.site)}/", EXPORT.format(filter_id=self._filter()))
        response = _post_export(self.session, url, calendar_id)
        if response.status_code != 200:
            raise IcError(
                f"HTTP {response.status_code} exporting the roster for school "
                f"{school_id}",
                response.status_code,
            )
        if "csv" not in response.headers.get("content-type", ""):
            raise IcError(f"no CSV exporting the roster for school {school_id}")
        return response.content.decode("utf-8-sig")

    def _calendar_id(self, code: str) -> str:
        pattern = re.compile(rf"\d{{2}}-\d{{2}}{re.escape(code)}")
        matches = [
            calendar_id
            for name, calendar_id in self.calendar_ids.items()
            if name == code or pattern.fullmatch(name)
        ]
        if len(matches) != 1:
            raise IcError(f"calendar {code}: {len(matches)} matches")
        return matches[0]

    def _filter(self) -> str:
        if self._filter_id is None:
            page = _get(self.session, f"{_base(self.site)}/{FILTERS}")
            soup = BeautifulSoup(page.text, "html.parser")
            ids = {
                str(tag.get("filterid"))
                for tag in soup.find_all(True)
                if tag.get("filterid")
                and tag.get("filtername") == self.site.roster_filter
            }
            if len(ids) != 1:
                raise IcError(f"roster filter: {len(ids)} matches")
            self._filter_id = ids.pop()
        return self._filter_id


def _base(site: IcSite) -> str:
    return site.base_url.rstrip("/")


def _xsrf(session: requests.Session) -> str:
    return session.cookies.get("XSRF-TOKEN") or ""


@_transient_retry
def _get(session: requests.Session, url: str) -> requests.Response:
    response = session.get(url, timeout=TIMEOUT)
    if response.status_code != 200:
        raise IcError(
            f"HTTP {response.status_code} loading an IC page", response.status_code
        )
    return response


@_transient_retry
def _post_export(
    session: requests.Session, url: str, calendar_id: str
) -> requests.Response:
    token = _xsrf(session)
    response = session.post(
        url,
        data={
            "adhocBypassScope": "true",
            "calendarID": calendar_id,
            "calendarIDs": calendar_id,
            "X-XSRF-TOKEN": token,
        },
        headers={"X-XSRF-TOKEN": token},
        timeout=EXPORT_TIMEOUT,
    )
    if response.status_code in TRANSIENT_STATUSES:
        raise IcError(f"HTTP {response.status_code} exporting", response.status_code)
    return response


def _login(
    session: requests.Session, site: IcSite, username: str, password: str
) -> None:
    _get(session, f"{_base(site)}/{site.app_name}.jsp")
    response = session.post(
        f"{_base(site)}/verify.jsp",
        data={
            "appName": site.app_name,
            "screen": "",
            "username": username,
            "password": password,
            "useCSRFProtection": "true",
        },
        timeout=TIMEOUT,
    )
    if "deviceauthorization" in response.url.lower():
        _continue_without_recognizing(session, response)


def _continue_without_recognizing(
    session: requests.Session, page: requests.Response
) -> None:
    """Press Continue on User Device Confirmation, leaving "recognize this
    device" unticked: proceed for this session only."""
    soup = BeautifulSoup(page.text, "html.parser")
    form = soup.find("form", id="form")
    if form is None:
        raise IcLoginError("device confirmation page without its form")
    base_tag = soup.find("base")
    base = base_tag.get("href") if base_tag and base_tag.get("href") else page.url
    data = {
        element["name"]: element.get("value", "")
        for element in form.find_all("input")
        if element.get("name") and element.get("type") == "hidden"
    }
    data["X-XSRF-TOKEN"] = _xsrf(session)
    session.post(
        urljoin(str(base), str(form.get("action") or "")), data=data, timeout=TIMEOUT
    )


def _calendar_ids(session: requests.Session, site: IcSite) -> dict[str, str]:
    """The Data Export wizard's calendar list: proof the login worked and
    the account may export."""
    page = _get(session, f"{_base(site)}/{WIZARD}")
    select = BeautifulSoup(page.text, "html.parser").find("select", id="calendarID")
    if select is None:
        raise IcLoginError("not logged in, or no Data Export rights")
    return {
        option.get_text(strip=True): str(option.get("value"))
        for option in select.find_all("option")
        if option.get("value")
    }


@contextmanager
def ic_session(
    site: IcSite, username: str, password: str, calendars: Mapping[str, str]
) -> Iterator[IcClient]:
    """Log into Infinite Campus and yield a client. The session simply
    ends; IC expires it."""
    with requests.Session() as session:
        _login(session, site, username, password)
        yield IcClient(
            session=session,
            site=site,
            calendars=calendars,
            calendar_ids=_calendar_ids(session, site),
        )


def ic_opener(
    secret: Callable[[str], str], site: IcSite, calendars: Mapping[str, str]
) -> RosterSourceOpener:
    """A RosterSourceOpener for the district's IC, logging in with the
    credentials from `secret`, read when first needed."""
    credentials: list[str] = []

    def open_rosters():
        if not credentials:
            credentials.extend(
                [secret("infinite-campus-username"), secret("infinite-campus-password")]
            )
        username, password = credentials
        return ic_session(site, username, password, calendars)

    return open_rosters
