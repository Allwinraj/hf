from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.core.storage import Storage
from app.deps import get_storage
from app.services.behaviors import list_behavior_versions
from app.services.catalog import CATALOG, catalog_entry

router = APIRouter(prefix="/agents", tags=["agents"])


@router.get("")
def list_agents() -> dict:
    return {"agents": CATALOG}


@router.get("/{name}")
def get_agent(name: str) -> dict:
    entry = catalog_entry(name)
    if entry is None:
        raise HTTPException(status_code=404, detail="unknown agent")
    return entry


@router.get("/{name}/versions")
def agent_versions(name: str, storage: Storage = Depends(get_storage)) -> dict:
    if catalog_entry(name) is None:
        raise HTTPException(status_code=404, detail="unknown agent")
    versions = list_behavior_versions(storage, name)
    return {
        "name": name,
        "versions": [
            {
                "version": item.behavior.version,
                "ref": item.ref,
                "modes": item.behavior.modes,
                "config": item.behavior.config,
            }
            for item in versions
        ],
    }
