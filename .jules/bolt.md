## 2024-05-18 - Optimized setup existence checks
**Learning:** Checking for application setup status using `select(User).limit(1)` is a minor performance anti-pattern. While the DB limits the query to a single row, SQLAlchemy still executes the overhead to fetch all columns and construct a full `User` model instance just to check for existence.
**Action:** When performing simple existence checks, select only the primary key, e.g., `select(User.id).limit(1)`. This minimizes data transfer and avoids ORM model construction overhead.
