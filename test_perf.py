import sys
import timeit
import random

class PlaybookEngineOld:
    def __init__(self, size=7):
        # We will make it scalable to show O(N) vs O(1)
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

# Import our updated real PlaybookEngine
from app.services.ai.playbook import PlaybookEngine

def run_benchmark():
    size = 100
    engine_old = PlaybookEngineOld(size)
    engine_new = PlaybookEngine()

    # Let's add some dummy playbooks to engine_new for testing using the public API
    from app.services.ai.playbook import ServicePlaybook
    for i in range(size):
        engine_new.add_playbook(
            ServicePlaybook(service=f'service_{i}', ports=[1000 + i, 2000 + i])
        )

    services = [f"service_{i}" for i in range(size)] + ["unknown_service"]
    ports = [1000 + i for i in range(size)] + [9999, None]

    test_cases = [(random.choice(services), random.choice(ports)) for _ in range(10000)]

    def test_lookup_old():
        for svc, port in test_cases:
            engine_old.get_playbook_for_service(svc, port)

    def test_lookup_new():
        for svc, port in test_cases:
            engine_new.get_playbook_for_service(svc, port)

    duration_old = timeit.timeit(test_lookup_old, number=100)
    duration_new = timeit.timeit(test_lookup_new, number=100)

    print(f"Old O(N) baseline: {duration_old:.4f} seconds")
    print(f"New O(1) optimized: {duration_new:.4f} seconds")
    print(f"Improvement: {(duration_old - duration_new) / duration_old * 100:.2f}%")

if __name__ == "__main__":
    run_benchmark()
