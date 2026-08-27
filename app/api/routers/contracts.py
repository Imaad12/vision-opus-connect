"""Contracts -- created once from an awarded project/quotation, then
moved through DRAFT -> ACTIVE -> COMPLETED, or terminated. Backed
entirely by `contract_service`; this router adds no rules of its own.

Deliberately no amendment/versioning endpoints, and no PUT for
value/currency -- see `Contract`'s docstring for why a post-signing value
change is a `ProjectVariation`, not a contract edit.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_permission
from app.api.schemas import ContractCreate, ContractRead
from app.services import contract_service, project_service
from app.services.errors import ValidationError

router = APIRouter(tags=["contracts"])


def _get_contract_or_404(session: Session, contract_id: int):
    contract = contract_service.get_contract(session, contract_id)
    if contract is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Contract not found.")
    return contract


@router.get("/projects/{project_id}/contract", response_model=ContractRead)
def get_contract_for_project(
    project_id: int,
    session: Session = Depends(get_db),
    _user=Depends(require_permission("contracts.view")),
) -> ContractRead:
    contract = contract_service.get_contract_for_project(session, project_id)
    if contract is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="This project has no contract.")
    return contract


@router.get("/contracts/{contract_id}", response_model=ContractRead)
def get_contract(
    contract_id: int,
    session: Session = Depends(get_db),
    _user=Depends(require_permission("contracts.view")),
) -> ContractRead:
    return _get_contract_or_404(session, contract_id)


@router.post(
    "/projects/{project_id}/contracts", response_model=ContractRead, status_code=status.HTTP_201_CREATED
)
def create_contract(
    project_id: int,
    payload: ContractCreate,
    session: Session = Depends(get_db),
    _user=Depends(require_permission("contracts.create")),
) -> ContractRead:
    project = project_service.get_project(session, project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found.")
    try:
        return contract_service.create_contract(session, project, **payload.model_dump())
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc


@router.post("/contracts/{contract_id}/activate", response_model=ContractRead)
def activate_contract(
    contract_id: int,
    session: Session = Depends(get_db),
    _user=Depends(require_permission("contracts.edit")),
) -> ContractRead:
    contract = _get_contract_or_404(session, contract_id)
    try:
        return contract_service.activate_contract(session, contract)
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc


@router.post("/contracts/{contract_id}/complete", response_model=ContractRead)
def complete_contract(
    contract_id: int,
    session: Session = Depends(get_db),
    _user=Depends(require_permission("contracts.edit")),
) -> ContractRead:
    contract = _get_contract_or_404(session, contract_id)
    try:
        return contract_service.complete_contract(session, contract)
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc


@router.post("/contracts/{contract_id}/terminate", response_model=ContractRead)
def terminate_contract(
    contract_id: int,
    session: Session = Depends(get_db),
    _user=Depends(require_permission("contracts.edit")),
) -> ContractRead:
    contract = _get_contract_or_404(session, contract_id)
    try:
        return contract_service.terminate_contract(session, contract)
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
