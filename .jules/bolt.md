## 2024-05-18 - Optimized setup existence checks
**Learning:** Checking for application setup status using `select(User).limit(1)` is a minor performance anti-pattern. While the DB limits the query to a single row, SQLAlchemy still executes the overhead to fetch all columns and construct a full `User` model instance just to check for existence.
**Action:** When performing simple existence checks, select only the primary key, e.g., `select(User.id).limit(1)`. This minimizes data transfer and avoids ORM model construction overhead.

## 2026-03-03 - Optimized AI Playbook Deduplication
**Learning:** Generating a large list of dictionaries just to iterate over them again and discard duplicates is inefficient. By checking for duplicates with a `set` *before* allocating the dictionary and appending it, we can achieve speedup and reduce memory allocation overhead.
**Action:** Whenever a unique set of complex objects (like dicts) is needed from a loop, check for uniqueness using a primitive key in a `set()` *before* constructing the complex object.
