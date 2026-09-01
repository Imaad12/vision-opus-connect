"""Contract lifecycle: created once from an awarded quotation, then moved
through DRAFT -> ACTIVE -> COMPLETED, or ACTIVE -> TERMINATED.

Deliberately does not duplicate the award logic in `quotation_service`:
a `Contract` can only be created for a `Project` that is already
`AWARDED` with a `winning_quotation_version_id` set, and its
`value`/`currency` are copied from the project at creation time, never
computed here.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.core.enums import ContractStatus, ProjectStatus
from app.models import Contract, Project, QuotationVersion
from app.services.errors import ValidationError

__all__ = [
    "ValidationError",
    "list_contracts",
    "get_contract",
    "get_contract_for_project",
    "create_contract",
    "activate_contract",
    "complete_contract",
    "terminate_contract",
]


def list_contracts(session: Session) -> list[Contract]:
    """All contracts, newest first -- the data behind the global
    Contracts page. Eagerly loads `project.client` for display, same
    pattern as `quotation_service.list_quotation_versions`."""
    stmt = (
        select(Contract)
        .options(joinedload(Contract.project).joinedload(Project.client))
        .where(Contract.is_deleted.is_(False))
        .order_by(Contract.id.desc())
    )
    return list(session.execute(stmt).scalars().all())


def get_contract(session: Session, contract_id: int) -> Contract | None:
    contract = session.get(Contract, contract_id)
    if contract is None or contract.is_deleted:
        return None
    return contract


def get_contract_for_project(session: Session, project_id: int) -> Contract | None:
    stmt = select(Contract).where(Contract.project_id == project_id, Contract.is_deleted.is_(False))
    return session.execute(stmt).scalars().first()


def create_contract(
    session: Session,
    project: Project,
    *,
    contract_number: str | None = None,
    signed_date: date | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    notes: str | None = None,
) -> Contract:
    if project.status != ProjectStatus.AWARDED or project.winning_quotation_version_id is None:
        raise ValidationError("A contract can only be created for an awarded project.")
    if project.contract_value is None:
        raise ValidationError("The awarded project has no contract value to record.")

    if get_contract_for_project(session, project.id) is not None:
        raise ValidationError("This project already has a contract.")

    quotation_version = session.get(QuotationVersion, project.winning_quotation_version_id)
    if quotation_version is None:
        raise ValidationError("The project's winning quotation version could not be found.")

    contract = Contract(
        project_id=project.id,
        quotation_version_id=quotation_version.id,
        contract_number=(contract_number or "").strip() or None,
        value=project.contract_value,
        currency=project.contract_currency,
        status=ContractStatus.DRAFT,
        signed_date=signed_date,
        start_date=start_date,
        end_date=end_date,
        notes=(notes or "").strip() or None,
    )
    session.add(contract)
    session.flush()
    return contract


def activate_contract(session: Session, contract: Contract) -> Contract:
    if contract.status != ContractStatus.DRAFT:
        raise ValidationError("Only a draft contract can be activated.")
    contract.status = ContractStatus.ACTIVE
    session.flush()
    return contract


def complete_contract(session: Session, contract: Contract) -> Contract:
    if contract.status != ContractStatus.ACTIVE:
        raise ValidationError("Only an active contract can be marked completed.")
    contract.status = ContractStatus.COMPLETED
    session.flush()
    return contract


def terminate_contract(session: Session, contract: Contract) -> Contract:
    if contract.status not in (ContractStatus.DRAFT, ContractStatus.ACTIVE):
        raise ValidationError("Only a draft or active contract can be terminated.")
    contract.status = ContractStatus.TERMINATED
    session.flush()
    return contract
