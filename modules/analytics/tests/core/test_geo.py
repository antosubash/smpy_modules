from types import SimpleNamespace

from sm_analytics.core.geo import GeoResolver


def test_geo_handles_missing_private_and_partial_results(tmp_path):
    resolver = GeoResolver(str(tmp_path / "missing.mmdb"), enabled=True)
    assert resolver.lookup("8.8.8.8").country == ""
    assert resolver.status()["available"] is False
    assert resolver.lookup("127.0.0.1").country == ""


def test_geo_reopens_on_atomic_replacement_and_closes(tmp_path):
    path = tmp_path / "geo.mmdb"
    path.write_text("one")
    readers = []

    class Reader:
        closed = False

        def __init__(self, filename):
            readers.append(self)

        def metadata(self):
            return SimpleNamespace(build_epoch=1700000000)

        def city(self, ip):
            return SimpleNamespace(
                country=SimpleNamespace(iso_code="AT", name="Austria"),
                subdivisions=SimpleNamespace(
                    most_specific=SimpleNamespace(iso_code="9", name="Vienna")
                ),
                city=SimpleNamespace(geoname_id=2761369, name="Vienna"),
            )

        def close(self):
            self.closed = True

    resolver = GeoResolver(str(path), enabled=True, reader_factory=Reader)
    location = resolver.lookup("8.8.8.8")
    assert (location.country, location.region, location.city) == ("AT", "AT-9", "2761369")
    assert resolver.lookup("2001:4860:4860::8888").city_name == "Vienna"
    replacement = tmp_path / "new.mmdb"
    replacement.write_text("two")
    replacement.replace(path)
    resolver.lookup("8.8.4.4")
    assert readers[0].closed and len(readers) == 2
    resolver.close()
    assert readers[-1].closed


def test_corrupt_database_and_partial_location_do_not_break_collection(tmp_path):
    path = tmp_path / "bad.mmdb"
    path.write_bytes(b"corrupt")

    def corrupt(_):
        raise ValueError("Invalid database")

    resolver = GeoResolver(str(path), enabled=True, reader_factory=corrupt)
    assert resolver.lookup("8.8.8.8").country == ""
    assert resolver.status()["available"] is False

    class Partial:
        def __init__(self, _):
            pass

        def metadata(self):
            return SimpleNamespace(build_epoch=1700000000)

        def city(self, _):
            return SimpleNamespace(
                country=SimpleNamespace(iso_code="AT", name="Austria"),
                subdivisions=SimpleNamespace(
                    most_specific=SimpleNamespace(iso_code=None, name=None)
                ),
                city=SimpleNamespace(geoname_id=None, name=None),
            )

        def close(self):
            pass

    resolver = GeoResolver(str(path), enabled=True, reader_factory=Partial)
    assert resolver.lookup("8.8.8.8").fields() == {
        "country": "AT",
        "country_name": "Austria",
        "region": "",
        "region_name": "",
        "city": "",
        "city_name": "",
    }
    resolver.close()


def test_lookup_corruption_marks_database_unavailable_until_replacement(tmp_path):
    path = tmp_path / "broken.mmdb"
    path.write_bytes(b"corrupt data after valid metadata")

    class Reader:
        def __init__(self, _):
            pass

        def metadata(self):
            return SimpleNamespace(build_epoch=1700000000)

        def city(self, _):
            raise ValueError("corrupt record")

        def close(self):
            pass

    resolver = GeoResolver(str(path), enabled=True, reader_factory=Reader)
    assert resolver.lookup("8.8.8.8").country == ""
    assert resolver.status()["available"] is False
