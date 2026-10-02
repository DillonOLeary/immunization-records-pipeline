"""A fake Infinite Campus: the staff login and the Data Export requests
the roster export makes.

It mirrors the parts that make the real flow tricky:
- the XSRF cookie, which must come back as a form field;
- a User Device Confirmation page after every login;
- calendars named with a school-year prefix, including "26-27PK" beside
  "26-27VPK-PK";
- a filter list to find the roster filter in;
- a form-POST export.

`app.state.ic` records every export (calendar codes) and every time a
client asked to register its device, which the pipeline must never do.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from fastapi import FastAPI, Form, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse

from .sample_data import roster_csv

XSRF = "mock-xsrf-token"
SESSION = "mock-ic-session"
ROSTER_FILTER = ("77", "MIIC Oct 2023")
CALENDARS = {  # name -> (IC calendar id, the school whose students it holds)
    "26-27FHMS": ("101", "2542"),
    "26-27GEMS": ("102", "2543"),
    "26-27PK": ("106", "2544"),
    "26-27VPK-PK": ("109", "default"),
}


@dataclass
class IcFaults:
    login_down: bool = False
    export_status: dict[str, int] = field(default_factory=dict)  # calendar -> HTTP
    short_roster: set[str] = field(default_factory=set)  # calendars: one student
    wrong_layout: set[str] = field(default_factory=set)  # calendars: other columns

    def clear(self) -> None:
        self.login_down = False
        self.export_status.clear()
        self.short_roster.clear()
        self.wrong_layout.clear()


@dataclass
class IcState:
    faults: IcFaults = field(default_factory=IcFaults)
    exports: list[str] = field(default_factory=list)
    devices_registered: int = 0

    def reset(self) -> None:
        self.faults.clear()
        self.exports.clear()
        self.devices_registered = 0


def _logged_in(request: Request) -> bool:
    return request.cookies.get("JSESSIONID") == SESSION


def add_ic_routes(
    app: FastAPI,
    base_url: str,
    credentials: tuple[str, str] = ("ic_user", "ic_password"),
) -> None:
    app.state.ic = IcState()
    login_page = "<html><title>Infinite Campus</title><form id='login'></form></html>"

    @app.get("/campus/{app_name}.jsp", response_class=HTMLResponse)
    async def login_form(app_name: str):
        response = HTMLResponse(login_page)
        response.set_cookie("XSRF-TOKEN", XSRF)
        return response

    @app.post("/campus/verify.jsp")
    async def verify(username: str = Form(...), password: str = Form(...)):
        if app.state.ic.faults.login_down:
            return Response(status_code=503)
        if (username, password) != credentials:
            return HTMLResponse(login_page)  # IC shows the login page again
        response = RedirectResponse("/campus/deviceAuthorization.xsl", status_code=302)
        response.set_cookie("device_pending", "1")
        return response

    @app.get("/campus/deviceAuthorization.xsl", response_class=HTMLResponse)
    async def device_page(request: Request):
        if request.cookies.get("device_pending") != "1":
            return HTMLResponse(login_page)
        return HTMLResponse(
            f"<html><head><base href='{base_url}/campus/'></head><body>"
            "<form id='form' action='verifyDevice.jsp' method='post'>"
            "<input type='hidden' name='token' value='device-token'>"
            "<input type='checkbox' name='deviceAccepted' value='true'>"
            "<input type='submit' value='Continue'></form></body></html>"
        )

    @app.post("/campus/verifyDevice.jsp")
    async def verify_device(request: Request):
        form = await request.form()
        if form.get("X-XSRF-TOKEN") != XSRF or form.get("token") != "device-token":
            return Response(status_code=403)
        if "deviceAccepted" in form:
            app.state.ic.devices_registered += 1
        response = RedirectResponse("/campus/sis", status_code=302)
        response.set_cookie("JSESSIONID", SESSION)
        return response

    @app.get("/campus/sis", response_class=HTMLResponse)
    async def landing():
        return HTMLResponse("<html><title>Infinite Campus</title></html>")

    @app.get("/campus/adhoc/dataWizard/dataWizard.xsl", response_class=HTMLResponse)
    async def wizard(request: Request):
        if not _logged_in(request):
            return HTMLResponse(login_page)
        options = "".join(
            f"<option value='{calendar_id}'>{name}</option>"
            for name, (calendar_id, _) in CALENDARS.items()
        )
        return HTMLResponse(f"<form><select id='calendarID'>{options}</select></form>")

    @app.get("/campus/adhoc/filters/filterList.xsl", response_class=HTMLResponse)
    async def filter_list(request: Request):
        if not _logged_in(request):
            return HTMLResponse(login_page)
        filter_id, name = ROSTER_FILTER
        return HTMLResponse(
            f"<table filterID='12' filterName='Attendance' filterType='query'></table>"
            f"<table filterID='{filter_id}' filterName='{name}' filterType='query'>"
            "</table>"
        )

    @app.post("/campus/extract/adhocDelimited.xsl")
    async def export(request: Request, delimiter: str):
        if not _logged_in(request) or request.headers.get("X-XSRF-TOKEN") != XSRF:
            return HTMLResponse(login_page)
        form = await request.form()
        by_id = {calendar_id: name for name, (calendar_id, _) in CALENDARS.items()}
        name = by_id.get(str(form.get("calendarID")))
        filter_id = request.query_params.get("filterID")
        if filter_id != ROSTER_FILTER[0] or delimiter != "pipe" or name is None:
            return Response(status_code=400)
        faults = app.state.ic.faults
        if name in faults.export_status:
            return Response(status_code=faults.export_status[name])
        app.state.ic.exports.append(name)
        text = roster_csv(CALENDARS[name][1])
        if name in faults.short_roster:
            text = "\n".join(text.splitlines()[:2]) + "\n"
        if name in faults.wrong_layout:
            text = "student|name\n1|x\n"
        return Response(
            content=text.encode(),
            media_type="application/csv;charset=utf-8",
            headers={"content-disposition": "attachment; filename=roster.csv"},
        )
