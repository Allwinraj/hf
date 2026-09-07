from __future__ import annotations

from app.core.storage import Storage
from app.models.pipeline import Pipeline
from app.models.run import Run


def save_pipeline(storage: Storage, pipeline: Pipeline) -> None:
    storage.write_json(pipeline.model_dump(mode="json"), "pipelines", f"{pipeline.id}.json")


def load_pipeline(storage: Storage, pipeline_id: str) -> Pipeline:
    return Pipeline.model_validate(storage.read_json("pipelines", f"{pipeline_id}.json"))


def save_run(storage: Storage, run: Run) -> None:
    storage.write_json(run.model_dump(mode="json"), "runs", f"{run.id}.json")


def load_run(storage: Storage, run_id: str) -> Run:
    return Run.model_validate(storage.read_json("runs", f"{run_id}.json"))


def list_pipelines(storage: Storage) -> list[Pipeline]:
    pipelines = []
    for path in storage.list("pipelines"):
        if path.suffix == ".json":
            pipelines.append(Pipeline.model_validate(storage.read_json("pipelines", path.name)))
    return pipelines
