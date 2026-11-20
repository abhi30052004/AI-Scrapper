from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, selectinload
from sqlalchemy import select
from ..db import get_db
from ..models import Site, SiteField
from ..schemas import SiteCreate, SiteOut

router = APIRouter(prefix="/api/sites", tags=["sites"])

@router.post("", response_model=SiteOut, status_code=201)
def create_site(payload: SiteCreate, db: Session = Depends(get_db)):
    url = str(payload.url)
    existing = db.scalar(select(Site).where(Site.url == url))
    if existing:
        raise HTTPException(409, "This website has already been added.")
    site = Site(name=payload.name or urlparse_name(url), url=url, run_frequency=payload.run_frequency, status="onboarding")
    for item in payload.fields:
        site.fields.append(SiteField(name=item.name, data_type=item.data_type, required=int(item.required), example_value=item.example_value))
    db.add(site)
    db.commit()
    db.refresh(site)
    return site

def urlparse_name(url: str) -> str:
    from urllib.parse import urlparse
    return urlparse(url).netloc or url

@router.get("", response_model=list[SiteOut])
def list_sites(db: Session = Depends(get_db)):
    return list(db.scalars(select(Site).options(selectinload(Site.fields)).order_by(Site.created_at.desc())).all())

@router.get("/{site_id}", response_model=SiteOut)
def get_site(site_id: int, db: Session = Depends(get_db)):
    site = db.scalar(select(Site).options(selectinload(Site.fields)).where(Site.id == site_id))
    if not site:
        raise HTTPException(404, "Website not found.")
    return site
