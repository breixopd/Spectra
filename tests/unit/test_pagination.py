"""
Tests for PaginatedResponse schema and pagination logic.
"""

from app.api.schemas import PaginatedResponse


class TestPaginatedResponse:
    """Tests for the PaginatedResponse Pydantic model."""

    def test_basic_construction(self):
        resp = PaginatedResponse(items=["a", "b"], total=2, page=1, per_page=10)
        assert resp.items == ["a", "b"]
        assert resp.total == 2
        assert resp.page == 1
        assert resp.per_page == 10

    def test_pages_auto_calculated(self):
        resp = PaginatedResponse(items=[], total=25, page=1, per_page=10)
        assert resp.pages == 3  # ceil(25/10) = 3

    def test_pages_exact_division(self):
        resp = PaginatedResponse(items=[], total=20, page=1, per_page=10)
        assert resp.pages == 2

    def test_pages_single_page(self):
        resp = PaginatedResponse(items=[], total=5, page=1, per_page=10)
        assert resp.pages == 1

    def test_pages_zero_total(self):
        resp = PaginatedResponse(items=[], total=0, page=1, per_page=10)
        assert resp.pages == 1  # max(1, ...) ensures at least 1

    def test_pages_override(self):
        resp = PaginatedResponse(items=[], total=50, page=1, per_page=10, pages=99)
        assert resp.pages == 99  # explicit override kept

    def test_large_dataset(self):
        resp = PaginatedResponse(items=[], total=10001, page=1, per_page=100)
        assert resp.pages == 101  # ceil(10001/100) = 101

    def test_per_page_one(self):
        resp = PaginatedResponse(items=[], total=5, page=1, per_page=1)
        assert resp.pages == 5

    def test_serialization_round_trip(self):
        resp = PaginatedResponse(items=[{"id": 1}], total=1, page=1, per_page=10)
        data = resp.model_dump()
        assert data["items"] == [{"id": 1}]
        assert data["total"] == 1
        assert data["page"] == 1
        assert data["per_page"] == 10
        assert data["pages"] == 1

    def test_items_can_be_dicts(self):
        items = [{"name": "a"}, {"name": "b"}]
        resp = PaginatedResponse(items=items, total=2, page=1, per_page=10)
        assert len(resp.items) == 2

    def test_items_can_be_empty(self):
        resp = PaginatedResponse(items=[], total=0, page=1, per_page=10)
        assert resp.items == []

    def test_page_and_per_page_stored(self):
        resp = PaginatedResponse(items=[], total=100, page=3, per_page=20)
        assert resp.page == 3
        assert resp.per_page == 20
        assert resp.pages == 5
