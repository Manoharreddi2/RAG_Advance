"""Evaluation results for the dashboard. Results are produced by ``python -m eval.run`` and imported verbatim."""
from __future__ import annotations

import json
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import EvalRun, User
from app.db.session import get_db
from app.deps import get_current_user, require_role

router = APIRouter(prefix="/eval", tags=["evaluation"])
RESULTS_DIR = Path(__file__).resolve().parents[2] / "eval" / "results"


@router.get("/runs")
async def list_runs(_: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    rows = await db.scalars(select(EvalRun).order_by(EvalRun.created_at.desc()))
    return [{"id": str(r.id), "name": r.name, "created_at": r.created_at, "metrics": r.metrics,
             "environment": r.environment, "config": r.config} for r in rows]


@router.get("/runs/{run_id}")
async def get_run(run_id: uuid.UUID, _: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    r = await db.get(EvalRun, run_id)
    if not r:
        raise HTTPException(404, "Run not found")
    return {"id": str(r.id), "name": r.name, "created_at": r.created_at, "metrics": r.metrics, "config": r.config,
            "environment": r.environment, "per_question": r.per_question}


async def import_results(db: AsyncSession, directory: Path = RESULTS_DIR) -> int:
    n = 0
    for path in sorted(directory.glob("*.json")):
        data = json.loads(path.read_text())
        if "run_name" not in data:
            continue
        exists = await db.scalar(select(EvalRun).where(EvalRun.name == data["run_name"]))
        if exists:
            continue
        db.add(EvalRun(name=data["run_name"], config={"configurations": data.get("configurations", [])},
                       metrics=data["summary"], per_question=data.get("per_question", []),
                       environment=data.get("environment", {})))
        n += 1
    await db.commit()
    return n


@router.post("/import", summary="Import eval/results/*.json produced by the evaluation runner")
async def import_runs(_: User = Depends(require_role("admin")), db: AsyncSession = Depends(get_db)):
    return {"imported": await import_results(db)}
