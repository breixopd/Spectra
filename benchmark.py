import timeit
import random

# We don't need the whole app, just the relevant code for benchmarking
class PlaybookEngineOld:
    def __init__(self, size=7):
        # Create dummy playbooks
        self.playbooks = [
            type('ServicePlaybook', (), {'service': f'service_{i}', 'ports': [1000 + i, 2000 + i]})()
            for i in range(size)
        ]

    def get_playbook_for_service(self, service: str, port: int | None = None):
        service_lower = service.lower()
        for pb in self.playbooks:
            if pb.service == service_lower:
                return pb
            if port and port in pb.ports:
                return pb
        return None

def run_benchmark():
    sizes = [10, 50, 100]

    for size in sizes:
        engine = PlaybookEngineOld(size)

        services = [f"service_{i}" for i in range(size)] + ["unknown_service"]
        ports = [1000 + i for i in range(size)] + [9999, None]

        test_cases = [(random.choice(services), random.choice(ports)) for _ in range(10000)]

        def test_lookup():
            for svc, port in test_cases:
                engine.get_playbook_for_service(svc, port)

        duration = timeit.timeit(test_lookup, number=100)
        print(f"Baseline for {size} playbooks: {duration:.4f} seconds")

# NOTE: This module is a legacy baseline benchmark kept for development reference.
# It is not intended to be executed as part of the production codebase or test suite.
# To run it manually, invoke `run_benchmark()` from an interactive session or a
# dedicated benchmarking harness, not from automated tooling.
