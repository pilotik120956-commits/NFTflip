import asyncio
import json as json_mod
import unittest

from adapters.base import HttpResponse
from adapters.portals import PortalsAdapter
from adapters.tonnel import TonnelAdapter
from config import get_settings
from models import Listing
from services.scanner import Scanner


class _FakeDb:
    async def set_market_health(self, *args, **kwargs):
        return None


class PortalsPaginationTests(unittest.TestCase):
    def test_paginates_until_short_page(self) -> None:
        settings = get_settings()
        adapter = PortalsAdapter(settings)

        async def resolve(collection):
            return {"id": 1, "name": collection}

        async def wait():
            return None

        adapter.resolve = resolve
        adapter._wait_slot = wait

        offsets: list[int] = []

        async def fake_request(method, url, *, params=None, json=None, headers=None):
            offset = int(dict(params)["offset"])
            offsets.append(offset)
            if offset == 0:
                items = [{"id": "p0", "price": 10.0, "attributes": [],
                         "external_collection_number": 1, "name": "X"},
                        {"id": "p1", "price": 11.0, "attributes": [],
                         "external_collection_number": 2, "name": "X"}]
            elif offset == 2:
                items = [{"id": "q0", "price": 20.0, "attributes": [],
                         "external_collection_number": 3, "name": "X"}]
            else:
                items = []
            return HttpResponse(200, {}, json_mod.dumps({"results": items}))

        adapter.http.request = fake_request

        result = asyncio.run(adapter.search("X", limit=2, pages=4))
        self.assertEqual([listing.id for listing in result], ["p0", "p1", "q0"])
        self.assertEqual(offsets, [0, 2])


class TonnelPaginationTests(unittest.TestCase):
    def test_paginates_until_short_page(self) -> None:
        settings = get_settings()
        adapter = TonnelAdapter(settings)

        pages_seen: list[int] = []

        async def fake_request(method, url, *, params=None, json=None, headers=None):
            page = json["page"]
            pages_seen.append(page)
            if page == 1:
                items = [{"gift_id": 1, "price": 10.0, "name": "X", "gift_num": 1}]
            elif page == 2:
                items = [{"gift_id": 2, "price": 20.0, "name": "X", "gift_num": 2}]
            else:
                items = []
            return HttpResponse(200, {}, json_mod.dumps(items))

        adapter.http.request = fake_request

        result = asyncio.run(adapter.search("X", limit=1, pages=4))
        self.assertEqual([listing.id for listing in result], ["1", "2"])
        self.assertEqual(pages_seen, [1, 2, 3])


class ScannerPassesPaginationTests(unittest.TestCase):
    def test_collect_forwards_pages_and_per_page(self) -> None:
        settings = get_settings()

        class FakeAdapter:
            name = "fake"
            display_name = "Fake"
            min_interval_sec = 0.0

            def __init__(self):
                self.calls: list[tuple[int, int]] = []

            async def search(self, collection, model=None, limit=30, *, pages=1):
                self.calls.append((limit, pages))
                return []

            @property
            def enabled(self):
                return True

        adapter = FakeAdapter()
        scanner = Scanner(settings, _FakeDb(), {"fake": adapter})
        asyncio.run(
            scanner._collect(
                [{"collection": "X", "model": None}],
                {"fake": adapter},
                pages=7,
                per_page=42,
            )
        )
        self.assertEqual(adapter.calls, [(42, 7)])


if __name__ == "__main__":
    unittest.main()
