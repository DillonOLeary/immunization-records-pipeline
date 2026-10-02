"""The district's config.json, parsed and bound to its adapters.

Config lives in the district's bucket (`config/config.json`), not in the
environment: it names schools and carries nurse contact emails, so it
stays out of Terraform and this repo. Parsing it here keeps every
adapter-specific value (AISR endpoints, the upload identity, per-school
upload metadata) out of the workflow, which receives only a `District`.

No code fallbacks on purpose: the upload identity was hardcoded to ISD
197 once, and a missing key must fail loudly rather than silently upload
under the wrong district.
"""

from __future__ import annotations

from collections.abc import Callable

from mn_immunization.adapters.infinite_campus.client import IcSite, ic_opener
from mn_immunization.adapters.miic.actions import DistrictInfo
from mn_immunization.adapters.miic.client import SchoolUpload, aisr_opener
from mn_immunization.workflow.ports import District, RosterSourceOpener, School

CONFIG_PATH = "config/config.json"


def district_from_config(config: dict, secret: Callable[[str], str]) -> District:
    """The district's schools, and a registry opener bound to its AISR
    endpoints, upload identity, and each school's upload metadata."""
    schools = tuple(School(id=s["id"], name=s["name"]) for s in config["schools"])
    uploads = {
        s["id"]: SchoolUpload(
            classification=s["classification"], email_contact=s["email"]
        )
        for s in config["schools"]
    }
    api = config["api"]
    return District(
        schools=schools,
        open_rosters=_roster_source(config, secret),
        open_registry=aisr_opener(
            secret,
            auth_url=api["auth_base_url"],
            api_url=api["aisr_api_base_url"],
            district=DistrictInfo(
                iddis=config["district"]["iddis"],
                s3_upload_host=api["s3_upload_host"],
            ),
            uploads=uploads,
        ),
    )


def _roster_source(
    config: dict, secret: Callable[[str], str]
) -> RosterSourceOpener | None:
    """Infinite Campus, when config names it; every school then needs its
    calendar code (`ic_calendar`, e.g. "FHMS"). Without it, rosters are
    uploaded by hand."""
    ic = config.get("infinite_campus")
    if ic is None:
        return None
    site = IcSite(
        base_url=ic["base_url"],
        app_name=ic["app_name"],
        roster_filter=ic["roster_filter"],
    )
    calendars = {s["id"]: s["ic_calendar"] for s in config["schools"]}
    return ic_opener(secret, site, calendars)
