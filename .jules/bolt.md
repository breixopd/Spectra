## 2024-05-18 - Optimized setup existence checks
**Learning:** Checking for application setup status using `select(User).limit(1)` is a minor performance anti-pattern. While the DB limits the query to a single row, SQLAlchemy still executes the overhead to fetch all columns and construct a full `User` model instance just to check for existence.
**Action:** When performing simple existence checks, select only the primary key, e.g., `select(User.id).limit(1)`. This minimizes data transfer and avoids ORM model construction overhead.

## 2026-03-03 - Optimized AI Playbook Deduplication
**Learning:** Generating a large list of dictionaries just to iterate over them again and discard duplicates is inefficient. By checking for duplicates with a `set` *before* allocating the dictionary and appending it, we can achieve speedup and reduce memory allocation overhead.
**Action:** Whenever a unique set of complex objects (like dicts) is needed from a loop, check for uniqueness using a primitive key in a `set()` *before* constructing the complex object.

## 2026-03-04 - Optimized CVE Vulnerability Lookup and Inference
**Learning:** Allocating dictionaries and performing generator comprehension checks like `any()` inside a hot path loop causes significant garbage collector and CPU overhead.
**Action:** Lift static mappings (like vulnerability types and severities) to pre-computed module-level global constants. Also, pre-calculate repeated string manipulations, such as `.lower()`, outside loops instead of applying them repeatedly on every item within the loop, and utilize fast looping constructs (like early returns inside explicit `for` loops).

## 2026-03-05 - Avoid deepcopy() in performance paths
**Learning:** `copy.deepcopy()` is incredibly slow due to recursive traversal and memoization overhead. When copying dictionaries to avoid mutating global constants, if you are only reassigning top-level keys rather than mutating nested lists/dicts in-place, a simple `.copy()` is significantly faster (~1-2µs vs ~15-30µs) and perfectly safe.
**Action:** Use `.copy()` instead of `deepcopy()` whenever possible when lifting static dictionaries to module-level scopes to avoid performance regressions.
