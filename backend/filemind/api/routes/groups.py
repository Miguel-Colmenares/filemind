"""Grupos de WhatsApp monitoreados (RF1)."""
from fastapi import APIRouter, Depends

from ..deps import get_fm, require_token, scope
from ..schemas import GroupsIn

router = APIRouter(prefix="/api/grupos", tags=["grupos"])


@router.get("")
def get_groups(fm=Depends(get_fm), groups=Depends(scope)):
    """Chats monitoreados; un miembro solo ve los de sus espacios de trabajo."""
    return {"grupos": [g for g in fm.groups if groups is None or g in groups]}


@router.put("", dependencies=[Depends(require_token)])
def put_groups(body: GroupsIn, fm=Depends(get_fm)):
    fm.audit.set_groups(body.grupos)
    fm.audit.log("grupos_configurados", groups=fm.groups)
    return {"grupos": fm.groups}


@router.get("/conteo", dependencies=[Depends(require_token)])
def counts(fm=Depends(get_fm)):
    """Cuántos archivos se han analizado de cada chat (para la página de chats)."""
    return fm.audit.counts_by_group()
