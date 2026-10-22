from __future__ import annotations

import pytest

from app.locks import ProcessingBusy, is_processing, processing_lock


def test_processing_lock_is_exclusive() -> None:
    assert not is_processing()
    with processing_lock():
        assert is_processing()
        with pytest.raises(ProcessingBusy):
            with processing_lock(blocking=False):
                pass
    assert not is_processing()


def test_run_pipeline_wrapper_holds_lock(monkeypatch) -> None:
    from app import pipeline

    seen: dict[str, bool] = {}

    def fake_pipeline(input_path, **kwargs):
        seen["busy"] = is_processing()
        return "done"

    monkeypatch.setattr(pipeline, "_run_pipeline", fake_pipeline)
    assert pipeline.run_pipeline("ignored.wav") == "done"
    assert seen["busy"] is True
    assert not is_processing()
