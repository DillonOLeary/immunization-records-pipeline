"""Production wiring, without the cloud: only the storage client and the
secret reader are replaced; the composition itself is the real one."""

import json

import mn_immunization.runtime.composition as composition
from mn_immunization.adapters.drive.delivery import GoogleDriveDelivery
from mn_immunization.workflow.settings import Settings
from tests.fakes import DISTRICT, FakeBucket, FakeStorageClient

CONFIG = {
    "api": {
        "auth_base_url": "https://auth.test",
        "aisr_api_base_url": "https://api.test",
        "s3_upload_host": "s3.test",
    },
    "district": {"iddis": "0197"},
    "schools": [
        {
            "id": "2542",
            "name": "Friendly Hills",
            "classification": "N",
            "email": "nurse@example.test",
            "ic_calendar": "FHMS",
        },
    ],
    "infinite_campus": {
        "base_url": "https://ic.test/campus",
        "app_name": "app",
        "roster_filter": "MIIC",
    },
}


def build(monkeypatch, **settings):
    bucket = FakeBucket("data-bucket")
    monkeypatch.setattr(
        composition, "get_storage_client", lambda: FakeStorageClient(bucket)
    )
    monkeypatch.setattr(composition, "secret_reader", lambda project: {}.__getitem__)
    settings = Settings(data_bucket="data-bucket", time_zone=DISTRICT, **settings)
    return composition.build_services(settings), bucket


def test_a_drive_folder_wires_drive_delivery_to_it(monkeypatch):
    services, _ = build(monkeypatch, drive_folder_id="folder-1")

    assert isinstance(services.delivery, GoogleDriveDelivery)
    assert services.delivery.folder_id == "folder-1"


def test_no_drive_folder_means_no_delivery(monkeypatch):
    services, _ = build(monkeypatch)

    assert services.delivery is None


def test_the_district_comes_from_the_buckets_config(monkeypatch):
    services, bucket = build(monkeypatch)
    bucket.write("config/config.json", json.dumps(CONFIG))

    district = services.load_district()

    assert [(s.id, s.name) for s in district.schools] == [("2542", "Friendly Hills")]
    assert district.open_rosters is not None
