"""Keyset pagination for the admin broadcast.

The broadcast used to call ``get_all()`` with no limit, materialising the whole
user table before sending the first message. ``iter_all`` streams it instead.

The loop is what these tests pin: that it advances past the last id it saw, that
it stops, and that it does not hold a database session while the caller is doing
slow work between rows — a broadcast runs for minutes.
"""

import pytest

from tgbot.database.models import User
from tgbot.database.orm import CRUDBase


def Row(pk: int) -> User:
    """A real mapped instance — iter_all builds a select() against the model,
    so a plain stand-in class is rejected by SQLAlchemy before the loop runs."""
    return User(id=pk)


class FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return list(self._rows)


class Recorder:
    """Serves rows from a fixed table, honouring the id > last filter."""

    def __init__(self, ids, batch_size):
        self.rows = [Row(i) for i in ids]
        self.batch_size = batch_size
        self.queries = 0
        self.open_sessions = 0
        self.max_open = 0
        self.sessions_opened = 0
        self._last_seen = None

    # -- session plumbing --------------------------------------------------
    def _get_session(self):
        recorder = self

        class Ctx:
            async def __aenter__(self_inner):
                recorder.open_sessions += 1
                recorder.sessions_opened += 1
                recorder.max_open = max(recorder.max_open, recorder.open_sessions)
                return self_inner

            async def __aexit__(self_inner, *exc):
                recorder.open_sessions -= 1
                return False

            async def execute(self_inner, query):
                recorder.queries += 1
                # Re-implement the predicate the query encodes.
                rows = recorder.rows
                if recorder._last_seen is not None:
                    rows = [r for r in rows if r.id > recorder._last_seen]
                page = rows[: recorder.batch_size]
                if page:
                    recorder._last_seen = page[-1].id
                return FakeResult(page)

        return Ctx()


def make_repo(ids, batch_size):
    repo = CRUDBase.__new__(CRUDBase)
    repo.model = User
    recorder = Recorder(ids, batch_size)
    repo._get_session = recorder._get_session
    return repo, recorder


@pytest.mark.parametrize(
    ("total", "batch"),
    [(0, 3), (1, 3), (3, 3), (4, 3), (7, 3), (10, 5), (10, 1)],
)
async def test_yields_every_row_exactly_once(total, batch):
    ids = list(range(1, total + 1))
    repo, _ = make_repo(ids, batch)
    seen = [row.id async for row in repo.iter_all(batch_size=batch)]
    assert seen == ids


async def test_a_full_final_page_costs_one_extra_empty_query_and_then_stops():
    """total == batch is the case where the loop could run forever."""
    repo, rec = make_repo([1, 2, 3], batch_size=3)
    seen = [r.id async for r in repo.iter_all(batch_size=3)]
    assert seen == [1, 2, 3]
    assert rec.queries == 2, "expected one full page plus one empty probe"


async def test_a_short_page_stops_without_another_query():
    repo, rec = make_repo([1, 2], batch_size=3)
    assert [r.id async for r in repo.iter_all(batch_size=3)] == [1, 2]
    assert rec.queries == 1, "a short page already proves there is no more"


async def test_no_session_is_held_while_the_caller_works_between_rows():
    """The whole point: a broadcast must not pin a connection for minutes."""
    repo, rec = make_repo(list(range(1, 8)), batch_size=3)
    observed = []
    async for _row in repo.iter_all(batch_size=3):
        observed.append(rec.open_sessions)
    assert observed and set(observed) == {0}, (
        "a database session was open while the caller was sending a message"
    )
    assert rec.max_open == 1, "sessions must not nest"


async def test_one_session_per_page_not_one_per_row():
    repo, rec = make_repo(list(range(1, 8)), batch_size=3)
    rows = [r.id async for r in repo.iter_all(batch_size=3)]
    assert len(rows) == 7
    # Pages are [1,2,3], [4,5,6], [7]. The last is short, which already proves
    # there is nothing after it, so no empty probe is needed: 3 reads for 7
    # rows. Anything approaching 7 would mean it degenerated to a read per row.
    assert rec.sessions_opened == 3
    assert rec.queries == 3


async def test_an_empty_table_yields_nothing_and_queries_once():
    repo, rec = make_repo([], batch_size=500)
    assert [r async for r in repo.iter_all()] == []
    assert rec.queries == 1
