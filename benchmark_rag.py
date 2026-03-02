import timeit
import random

class MockDocument:
    def __init__(self, doc_type):
        self.doc_type = doc_type

class MockResult:
    def __init__(self, doc_type):
        self.document = MockDocument(doc_type)

def run_benchmark():
    # Setup test data
    doc_types_pool = [f"type_{i}" for i in range(100)]

    # Test cases: Small N, Large N
    for n in [10, 100, 1000, 10000]:
        results = [MockResult(random.choice(doc_types_pool)) for _ in range(n)]

        # doc_types filter list
        doc_types_list = [f"type_{i}" for i in range(20)]
        doc_types_set = set(doc_types_list)

        # Original (List)
        def original_impl():
            return [r for r in results if r.document.doc_type in doc_types_list]

        # Optimized (Set)
        def optimized_impl():
            # In practice we'd convert it once: doc_types_set = set(doc_types)
            return [r for r in results if r.document.doc_type in doc_types_set]

        # Including set conversion
        def optimized_with_conversion_impl():
            dt_set = set(doc_types_list)
            return [r for r in results if r.document.doc_type in dt_set]

        orig_time = timeit.timeit(original_impl, number=1000)
        opt_time = timeit.timeit(optimized_impl, number=1000)
        opt_conv_time = timeit.timeit(optimized_with_conversion_impl, number=1000)

        print(f"--- N={n} Results ---")
        print(f"Original (List): {orig_time:.5f}s")
        print(f"Optimized (Set): {opt_time:.5f}s (Speedup: {orig_time/opt_time:.2f}x)")
        print(f"Optimized with conversion: {opt_conv_time:.5f}s (Speedup: {orig_time/opt_conv_time:.2f}x)\n")

if __name__ == "__main__":
    run_benchmark()
