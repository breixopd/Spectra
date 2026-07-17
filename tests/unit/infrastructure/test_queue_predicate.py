from sqlalchemy.dialects import postgresql

import spectra_infra.queue as queue_module


def test_claimable_job_predicate_compiles_for_postgresql() -> None:
    predicate_factory = getattr(queue_module, "_claimable_job_predicate", None)

    assert callable(predicate_factory), "queue worker must expose its claimable-job predicate"

    sql = str(
        predicate_factory().compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )
    assert "status = 'queued'" in sql
    assert "status = 'pending'" in sql
    assert "next_retry_at" in sql
